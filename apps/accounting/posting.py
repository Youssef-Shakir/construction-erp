"""
Posting engine for journal entries.

This module provides the core functionality for creating and posting
journal entries atomically, with validation that debits == credits.
"""
from contextvars import ContextVar
from decimal import Decimal
from functools import wraps

from django.db import transaction
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import Journal, JournalEntry, JournalLine, Account


class PostingError(Exception):
    """Raised when posting validation fails."""
    pass


_ALLOW_INACTIVE = ContextVar('allow_inactive_accounts', default=False)


def locked_document(method):
    """
    Decorator for document post()/cancel()/close() methods.

    Opens a transaction, locks the document row (SELECT ... FOR UPDATE) and
    refreshes its status from the database before the method runs. Without
    this, a double-click or two users posting the same draft at once would
    both see status='draft' and create two journal entries (doubling the
    ledger). On PostgreSQL the second request waits, then sees 'posted' and
    is rejected.
    """
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with transaction.atomic():
            if self.pk:
                current = (
                    type(self).objects.select_for_update()
                    .only('status', 'journal_entry')
                    .get(pk=self.pk)
                )
                self.status = current.status
                self.journal_entry_id = current.journal_entry_id
            return method(self, *args, **kwargs)
    return wrapper


def create_journal_entry(
    journal: Journal,
    date,
    lines: list,
    reference: str = '',
    memo: str = '',
    user=None,
    auto_post: bool = True,
) -> JournalEntry:
    """
    Create a journal entry with the given lines.

    Args:
        journal: The Journal to post to
        date: Entry date
        lines: List of dicts with keys:
            - account: Account instance or account code
            - debit: Decimal amount (default 0)
            - credit: Decimal amount (default 0)
            - description: Optional line description
            - partner: Optional Partner instance
            - project: Optional Project instance
        reference: Document reference (e.g., "INV-000001")
        memo: Entry description/memo
        user: User creating the entry
        auto_post: If True, post immediately after creation

    Returns:
        JournalEntry instance

    Raises:
        PostingError: If validation fails
    """
    if len(lines) < 2:
        raise PostingError('القيد يجب أن يحتوي على سطرين على الأقل')

    # Calculate totals
    total_debit = Decimal('0.00')
    total_credit = Decimal('0.00')

    for line in lines:
        debit = line.get('debit', Decimal('0.00'))
        credit = line.get('credit', Decimal('0.00'))

        if not isinstance(debit, Decimal):
            debit = Decimal(str(debit))
        if not isinstance(credit, Decimal):
            credit = Decimal(str(credit))

        total_debit += debit
        total_credit += credit

    # Validate balance
    if total_debit != total_credit:
        raise PostingError(
            f'القيد غير متوازن: مدين {total_debit} != دائن {total_credit}'
        )

    if total_debit == 0:
        raise PostingError('مجموع القيد لا يمكن أن يكون صفراً')

    with transaction.atomic():
        # Create entry
        entry = JournalEntry.objects.create(
            journal=journal,
            entry_number=journal.get_next_entry_number(),
            date=date,
            reference=reference,
            memo=memo,
            created_by=user,
        )

        # Create lines
        for i, line_data in enumerate(lines, start=1):
            account = line_data['account']
            if isinstance(account, str):
                try:
                    account = Account.objects.get(code=account)
                except Account.DoesNotExist:
                    raise PostingError(f'الحساب {account} غير موجود')
            if not account.is_active and not _ALLOW_INACTIVE.get():
                raise PostingError(f'الحساب {account} غير نشط - لا يمكن الترحيل عليه')

            debit = line_data.get('debit', Decimal('0.00'))
            credit = line_data.get('credit', Decimal('0.00'))

            if not isinstance(debit, Decimal):
                debit = Decimal(str(debit))
            if not isinstance(credit, Decimal):
                credit = Decimal(str(credit))

            # Skip zero lines
            if debit == 0 and credit == 0:
                continue

            line = JournalLine(
                entry=entry,
                line_number=i,
                account=account,
                description=line_data.get('description', ''),
                debit=debit,
                credit=credit,
                partner=line_data.get('partner'),
                project=line_data.get('project'),
            )

            # Validate line
            try:
                line.clean()
            except ValidationError as e:
                raise PostingError(str(e))

            line.save()

        # Post if requested
        if auto_post:
            post_entry(entry, user)

    return entry


def post_entry(entry: JournalEntry, user=None) -> None:
    """
    Post a journal entry (mark as posted).

    Args:
        entry: JournalEntry to post
        user: User posting the entry

    Raises:
        PostingError: If entry is already posted or unbalanced
    """
    if entry.is_posted:
        raise PostingError('القيد مرحّل بالفعل')

    if not entry.is_balanced:
        raise PostingError('القيد غير متوازن')

    if entry.lines.count() < 2:
        raise PostingError('القيد يجب أن يحتوي على سطرين على الأقل')

    entry.is_posted = True
    entry.posted_at = timezone.now()
    entry.posted_by = user
    entry.save()


def reverse_entry(entry: JournalEntry, date, user=None, memo: str = '') -> JournalEntry:
    """
    Create a reversal entry for an existing posted entry.

    Args:
        entry: JournalEntry to reverse
        date: Date for the reversal entry
        user: User creating the reversal
        memo: Optional memo for reversal

    Returns:
        New JournalEntry that reverses the original

    Raises:
        PostingError: If entry is not posted or already reversed
    """
    with transaction.atomic():
        # Lock the original so two concurrent reversals can't both succeed.
        locked = JournalEntry.objects.select_for_update().get(pk=entry.pk)

        if not locked.is_posted:
            raise PostingError('لا يمكن إلغاء قيد غير مرحّل')

        if locked.is_reversed:
            raise PostingError('القيد ملغي بالفعل')

        # Create reversal lines (swap debits and credits)
        reversal_lines = []
        for line in locked.lines.select_related('account'):
            reversal_lines.append({
                'account': line.account,
                'debit': line.credit,  # Swap
                'credit': line.debit,  # Swap
                'description': f'إلغاء: {line.description}' if line.description else 'إلغاء',
                'partner': line.partner,
                'project': line.project,
            })

        reversal = _create_entry_allowing_inactive(
            journal=locked.journal,
            date=date,
            lines=reversal_lines,
            reference=f'REV-{locked.entry_number}',
            memo=memo or f'إلغاء القيد {locked.entry_number}',
            user=user,
        )

        # Link entries
        reversal.reverses = locked
        reversal.save()

        locked.is_reversed = True
        locked.reversed_by = reversal
        locked.save()

    # Keep the caller's instance in sync with the database.
    entry.is_reversed = True
    entry.reversed_by = reversal
    return reversal


def _create_entry_allowing_inactive(journal, date, lines, reference, memo, user):
    """
    Reversals must always be possible, even if an account was deactivated
    after the original posting, so temporarily skip the is_active check.
    """
    token = _ALLOW_INACTIVE.set(True)
    try:
        return create_journal_entry(
            journal=journal, date=date, lines=lines, reference=reference,
            memo=memo, user=user, auto_post=True,
        )
    finally:
        _ALLOW_INACTIVE.reset(token)


def _money_sum(field, condition):
    return Coalesce(
        Sum(field, filter=condition),
        Value(Decimal('0.00')),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )


def accounts_with_balances(*, as_of_date=None, before_date=None, project=None, type_codes=None):
    """
    Accounts annotated with posted debit/credit totals and a signed `net`
    balance in the account's normal direction - computed in ONE SQL query.

    Includes inactive accounts (a deactivated account with a balance must
    still appear in reports or the trial balance stops balancing).

    Args:
        as_of_date: include lines dated on/before this date
        before_date: include lines strictly before this date (opening balances)
        project: restrict to lines tagged with this project
        type_codes: restrict to these AccountType codes
    """
    cond = Q(journal_lines__entry__is_posted=True)
    if as_of_date:
        cond &= Q(journal_lines__entry__date__lte=as_of_date)
    if before_date:
        cond &= Q(journal_lines__entry__date__lt=before_date)
    if project is not None:
        cond &= Q(journal_lines__project=project)

    qs = Account.objects.select_related('account_type').annotate(
        debit_total=_money_sum('journal_lines__debit', cond),
        credit_total=_money_sum('journal_lines__credit', cond),
    ).order_by('code')
    if type_codes:
        qs = qs.filter(account_type__code__in=type_codes)

    accounts = list(qs)
    for acc in accounts:
        if acc.account_type.normal_balance == 'debit':
            acc.net = acc.debit_total - acc.credit_total
        else:
            acc.net = acc.credit_total - acc.debit_total
    return accounts


def get_account_balance(account: Account, as_of_date=None, before_date=None) -> Decimal:
    """
    Signed balance of one account in its normal direction.

    `before_date` excludes that day itself - use it for ledger opening balances.
    """
    lines = account.journal_lines.filter(entry__is_posted=True)
    if as_of_date:
        lines = lines.filter(entry__date__lte=as_of_date)
    if before_date:
        lines = lines.filter(entry__date__lt=before_date)
    totals = lines.aggregate(d=Sum('debit'), c=Sum('credit'))
    debit = totals['d'] or Decimal('0.00')
    credit = totals['c'] or Decimal('0.00')
    if account.account_type.normal_balance == 'debit':
        return debit - credit
    return credit - debit


def get_trial_balance(as_of_date=None) -> dict:
    """
    Trial balance - every account with activity, its balance placed in the
    debit or credit column according to its sign.
    """
    result = []
    total_debit = Decimal('0.00')
    total_credit = Decimal('0.00')

    for account in accounts_with_balances(as_of_date=as_of_date):
        raw = account.debit_total - account.credit_total  # >0 = debit balance
        if raw == 0:
            continue
        debit_balance = raw if raw > 0 else Decimal('0.00')
        credit_balance = -raw if raw < 0 else Decimal('0.00')
        result.append({
            'account': account,
            'debit': debit_balance,
            'credit': credit_balance,
        })
        total_debit += debit_balance
        total_credit += credit_balance

    return {
        'accounts': result,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'is_balanced': total_debit == total_credit,
    }


def _section(accounts):
    """[{'account', 'balance'}] for non-zero accounts + signed total."""
    rows = [{'account': a, 'balance': a.net} for a in accounts if a.net != 0]
    return rows, sum((r['balance'] for r in rows), Decimal('0.00'))


def get_income_statement(as_of_date=None, project=None) -> dict:
    """
    Income statement (revenue, expenses, net income).

    Balances are SIGNED in the account's normal direction: a revenue account
    with net debits (e.g. a refund) reduces revenue instead of being shown
    as positive.

    Args:
        as_of_date: Optional cut-off date (defaults to today)
        project: Optional Project to scope the statement to (per-project P&L)
    """
    if as_of_date is None:
        as_of_date = timezone.now().date()

    revenue_data, total_revenue = _section(
        accounts_with_balances(as_of_date=as_of_date, project=project, type_codes=['revenue'])
    )
    expense_data, total_expenses = _section(
        accounts_with_balances(as_of_date=as_of_date, project=project, type_codes=['expense'])
    )

    return {
        'as_of_date': as_of_date,
        'revenue_data': revenue_data,
        'expense_data': expense_data,
        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'net_income': total_revenue - total_expenses,
    }


def get_balance_sheet(as_of_date=None) -> dict:
    """
    Balance sheet with signed balances. Current-period earnings
    (revenue - expenses to date) are shown inside equity so that
    assets == liabilities + equity whenever the ledger balances.
    """
    if as_of_date is None:
        as_of_date = timezone.now().date()

    accounts = accounts_with_balances(as_of_date=as_of_date)
    by_type = {}
    for acc in accounts:
        by_type.setdefault(acc.account_type.code, []).append(acc)

    asset_data, total_assets = _section(by_type.get('asset', []))
    liability_data, total_liabilities = _section(by_type.get('liability', []))
    equity_data, total_equity = _section(by_type.get('equity', []))
    _, total_revenue = _section(by_type.get('revenue', []))
    _, total_expenses = _section(by_type.get('expense', []))

    retained_earnings = total_revenue - total_expenses
    total_equity_with_retained = total_equity + retained_earnings

    return {
        'as_of_date': as_of_date,
        'asset_data': asset_data,
        'liability_data': liability_data,
        'equity_data': equity_data,
        'total_assets': total_assets,
        'total_liabilities': total_liabilities,
        'total_equity': total_equity,
        'retained_earnings': retained_earnings,
        'total_equity_with_retained': total_equity_with_retained,
        'total_liabilities_and_equity': total_liabilities + total_equity_with_retained,
        'is_balanced': total_assets == total_liabilities + total_equity_with_retained,
    }
