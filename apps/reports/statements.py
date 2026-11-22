"""
Account statements (كشف حساب) built from the ledger, so they always agree
with the balance sheet, receivables and payables:

- customer  -> Accounts Receivable (1100) lines for that customer
- supplier  -> Accounts Payable    (2000) lines for that supplier
- employee  -> Advances to PMs     (1200) lines for that employee (كشف السلف)

Only posted entries count. A cancelled document and its reversal cancel each
other out, so both are left out of the listing (the balance is identical).
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from apps.accounting.models import JournalLine

ZERO = Decimal('0.00')

CONTROL_ACCOUNT = {'customer': '1100', 'supplier': '2000', 'employee': '1200'}

STATEMENT_TITLE = {
    'customer': 'كشف حساب عميل',
    'supplier': 'كشف حساب مورد',
    'employee': 'كشف حساب سلف',
}

# What a positive / negative closing balance means, per partner type
BALANCE_MEANING = {
    'customer': ('مستحق لنا على العميل', 'رصيد دائن للعميل (دفعات مقدمة)'),
    'supplier': ('مستحق للمورد علينا', 'رصيد مدين على المورد'),
    'employee': ('عهدة لدى الموظف لم تُسوَّ', 'مستحق للموظف'),
}


@dataclass
class StatementRow:
    date: date
    number: str
    description: str
    project: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


@dataclass
class Statement:
    partner: object
    account_code: str
    date_from: date | None
    date_to: date | None
    opening: Decimal = ZERO
    rows: list = field(default_factory=list)
    total_debit: Decimal = ZERO
    total_credit: Decimal = ZERO
    closing: Decimal = ZERO

    @property
    def title(self):
        return STATEMENT_TITLE.get(self.partner.type, 'كشف حساب')

    @property
    def closing_meaning(self):
        positive, negative = BALANCE_MEANING.get(self.partner.type, ('', ''))
        if self.closing > 0:
            return positive
        if self.closing < 0:
            return negative
        return 'الحساب مسدّد بالكامل'


def _ledger_lines(partner, account_code, project=None):
    lines = JournalLine.objects.filter(
        account__code=account_code,
        partner=partner,
        entry__is_posted=True,
        entry__is_reversed=False,        # cancelled originals...
        entry__reverses__isnull=True,    # ...and their reversals net to zero
    )
    if project is not None:
        lines = lines.filter(project=project)
    return lines


def partner_statement(partner, date_from=None, date_to=None, project=None):
    """Opening balance, dated movements with running balance, closing balance."""
    account_code = CONTROL_ACCOUNT.get(partner.type)
    st = Statement(partner=partner, account_code=account_code, date_from=date_from, date_to=date_to)
    if account_code is None:
        return st

    # Customers and employees owe us when debited; we owe suppliers when credited
    sign = Decimal(-1) if partner.type == 'supplier' else Decimal(1)
    lines = _ledger_lines(partner, account_code, project)

    if date_from:
        money = DecimalField(max_digits=18, decimal_places=2)
        before = lines.filter(entry__date__lt=date_from).aggregate(
            d=Coalesce(Sum('debit'), Value(ZERO), output_field=money),
            c=Coalesce(Sum('credit'), Value(ZERO), output_field=money),
        )
        st.opening = sign * (before['d'] - before['c'])
        lines = lines.filter(entry__date__gte=date_from)
    if date_to:
        lines = lines.filter(entry__date__lte=date_to)

    running = st.opening
    for line in (lines.select_related('entry', 'project')
                 .order_by('entry__date', 'entry__id', 'line_number')):
        running += sign * (line.debit - line.credit)
        st.total_debit += line.debit
        st.total_credit += line.credit
        st.rows.append(StatementRow(
            date=line.entry.date,
            number=line.entry.reference or line.entry.entry_number,
            description=line.description or line.entry.memo,
            project=line.project.code if line.project else '',
            debit=line.debit,
            credit=line.credit,
            balance=running,
        ))
    st.closing = running
    return st


def employee_advances_summary(partner):
    """Per-advance settlement table for an employee (all non-draft advances)."""
    from apps.advances.models import CashAdvance

    advances = (CashAdvance.objects.filter(recipient=partner)
                .exclude(status__in=['draft', 'cancelled'])
                .select_related('project').order_by('date', 'id'))
    rows, totals = [], {'amount': ZERO, 'expenses': ZERO, 'returned': ZERO, 'remaining': ZERO}
    for adv in advances:
        row = {
            'advance': adv,
            'amount': adv.amount,
            'expenses': adv.total_expenses,
            'returned': adv.total_returned,
            'remaining': adv.remaining,
        }
        for key in totals:
            totals[key] += row[key]
        rows.append(row)
    return rows, totals


def advance_statement(advance):
    """Everything about one advance: expenses spent from it, cash returned, remaining."""
    from apps.expenses.models import Expense

    expenses = (Expense.objects.filter(advance=advance, status='posted')
                .select_related('account', 'project', 'partner').order_by('date', 'id'))
    returns = advance.returns.filter(status='posted').order_by('date', 'id')
    return {
        'advance': advance,
        'expenses': expenses,
        'returns': returns,
        'total_expenses': advance.total_expenses,
        'total_returned': advance.total_returned,
        'remaining': advance.remaining,
    }
