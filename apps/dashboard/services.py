"""
Dashboard queries. Everything is aggregated in SQL (no per-invoice Python
loops), and every figure is derived from posted documents / journal lines.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import (
    Count, DecimalField, ExpressionWrapper, F, OuterRef, Q, Subquery, Sum, Value,
)
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

ZERO = Decimal('0.00')
MONEY = DecimalField(max_digits=18, decimal_places=2)

# Cash & bank accounts (same codes the payment form offers)
CASH_ACCOUNT_CODES = ('1000', '1010')

AGING_BUCKETS = [
    ('current', 'غير مستحق'),
    ('d30', '1-30 يوم'),
    ('d60', '31-60 يوم'),
    ('d90', '61-90 يوم'),
    ('d90p', '+90 يوم'),
]


def _money(expr):
    return Coalesce(expr, Value(ZERO), output_field=MONEY)


def with_outstanding(qs):
    """Posted invoices/bills annotated with `paid` and `outstanding` (> 0 only)."""
    from apps.payments.models import PaymentAllocation

    ct = ContentType.objects.get_for_model(qs.model)
    paid = (
        PaymentAllocation.objects
        .filter(content_type=ct, object_id=OuterRef('pk'), payment__status='posted')
        .values('object_id')
        .annotate(total=Sum('amount'))
        .values('total')
    )
    return (
        qs.filter(status='posted')
        .annotate(paid=_money(Subquery(paid, output_field=MONEY)))
        .annotate(outstanding=ExpressionWrapper(F('amount') - F('paid'), output_field=MONEY))
        .filter(outstanding__gt=0)
    )


def aging(qs, today):
    """Outstanding amounts split into aging buckets by days past due date."""
    def bucket(cond):
        return _money(Sum('outstanding', filter=cond))

    totals = with_outstanding(qs).aggregate(
        total=_money(Sum('outstanding')),
        count=Count('pk'),
        current=bucket(Q(due_date__gte=today)),
        d30=bucket(Q(due_date__lt=today, due_date__gte=today - timedelta(days=30))),
        d60=bucket(Q(due_date__lt=today - timedelta(days=30), due_date__gte=today - timedelta(days=60))),
        d90=bucket(Q(due_date__lt=today - timedelta(days=60), due_date__gte=today - timedelta(days=90))),
        d90p=bucket(Q(due_date__lt=today - timedelta(days=90))),
    )
    totals['overdue'] = totals['total'] - totals['current']
    totals['buckets'] = [
        {
            'key': key, 'label': label, 'amount': totals[key],
            'pct': int(totals[key] * 100 / totals['total']) if totals['total'] else 0,
        }
        for key, label in AGING_BUCKETS
    ]
    return totals


def cash_position():
    """Balances of the cash and bank accounts, from the ledger."""
    from apps.accounting.posting import accounts_with_balances

    accounts = [a for a in accounts_with_balances(type_codes=['asset']) if a.code in CASH_ACCOUNT_CODES]
    return {'accounts': accounts, 'total': sum((a.net for a in accounts), ZERO)}


def open_advances():
    """Posted advances with their unsettled balance (advance - expenses - returns)."""
    from apps.advances.models import AdvanceReturn, CashAdvance
    from apps.expenses.models import Expense

    spent = (
        Expense.objects.filter(advance=OuterRef('pk'), status='posted')
        .values('advance').annotate(t=Sum('amount')).values('t')
    )
    returned = (
        AdvanceReturn.objects.filter(advance=OuterRef('pk'), status='posted')
        .values('advance').annotate(t=Sum('amount')).values('t')
    )
    rows = list(
        CashAdvance.objects.filter(status='posted')
        .select_related('recipient', 'project')
        .annotate(
            spent=_money(Subquery(spent, output_field=MONEY)),
            returned=_money(Subquery(returned, output_field=MONEY)),
        )
        .annotate(open_amount=ExpressionWrapper(F('amount') - F('spent') - F('returned'), output_field=MONEY))
        .filter(open_amount__gt=0)
        .order_by('date')
    )
    today = timezone.localdate()
    for adv in rows:
        adv.days_open = (today - adv.date).days
    return {'rows': rows, 'total': sum((a.open_amount for a in rows), ZERO), 'count': len(rows)}


def month_to_date(today):
    """Revenue, costs and net this month vs the same days of last month (ledger)."""
    from apps.accounting.models import JournalLine

    start = today.replace(day=1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)

    def period(date_from, date_to):
        agg = JournalLine.objects.filter(
            entry__is_posted=True, entry__date__gte=date_from, entry__date__lte=date_to,
        ).aggregate(
            revenue=_money(Sum(F('credit') - F('debit'), filter=Q(account__account_type__code='revenue'))),
            costs=_money(Sum(F('debit') - F('credit'), filter=Q(account__account_type__code='expense'))),
        )
        agg['net'] = agg['revenue'] - agg['costs']
        return agg

    same_day_prev = min(prev_start + timedelta(days=today.day - 1), prev_end)
    return {
        'start': start,
        'current': period(start, today),
        'previous': period(prev_start, same_day_prev),
    }


def project_summary(limit=8):
    """Active projects: revenue / costs / margin / receivable from the ledger + budget use."""
    from apps.accounting.models import JournalLine
    from apps.projects.models import Project

    projects = list(
        Project.objects.filter(status='active').select_related('customer').order_by('code')[:limit]
    )
    if not projects:
        return []

    figures = {
        row['project']: row
        for row in JournalLine.objects.filter(entry__is_posted=True, project__in=projects)
        .values('project')
        .annotate(
            revenue=_money(Sum(F('credit') - F('debit'), filter=Q(account__account_type__code='revenue'))),
            costs=_money(Sum(F('debit') - F('credit'), filter=Q(account__account_type__code='expense'))),
        )
    }
    # Receivables per project come from invoices (outstanding after allocated
    # payments): payment journal lines credit AR by partner only, not project.
    from apps.invoicing.models import Invoice
    receivable = {
        row['project']: row['total']
        for row in with_outstanding(Invoice.objects.filter(project__in=projects))
        .values('project').annotate(total=Sum('outstanding'))
    }
    for p in projects:
        f = figures.get(p.pk, {})
        p.dash_revenue = f.get('revenue', ZERO)
        p.dash_costs = f.get('costs', ZERO)
        p.dash_margin = p.dash_revenue - p.dash_costs
        p.dash_receivable = receivable.get(p.pk, ZERO)
        p.dash_budget_pct = int(p.dash_costs * 100 / p.budget) if p.budget else None
        p.dash_budget_bar = max(0, min(p.dash_budget_pct or 0, 100))
    return projects


def _n(count, one, many):
    """Arabic-friendly count phrase: 'فاتورة واحدة' / '3 فواتير'."""
    return one if count == 1 else f'{count} {many}'


def attention_items(user, today):
    """Things to act on, written as plain sentences for a non-accountant owner."""
    from apps.accounts.permissions import can_manage_scan_inbox, can_post_document
    from apps.advances.models import CashAdvance
    from apps.core.attachments import inbox_items
    from apps.expenses.models import Expense, ExpenseBatch
    from apps.invoicing.models import Bill, Invoice
    from apps.payments.models import Payment

    items = []

    def add(text, url, action, level='info', amount=None):
        items.append({'text': text, 'url': url, 'action': action, 'level': level, 'amount': amount})

    if can_post_document(user):
        overdue = with_outstanding(Invoice.objects.filter(due_date__lt=today)).aggregate(
            n=Count('pk'), amt=Sum('outstanding'))
        if overdue['n']:
            add(f"{_n(overdue['n'], 'زبون تأخر', 'زبائن تأخروا')} في الدفع",
                reverse('accounting:receivables'), 'تابع التحصيل', 'danger', overdue['amt'])

        due = with_outstanding(Bill.objects.filter(due_date__lte=today + timedelta(days=7))).aggregate(
            n=Count('pk'), amt=Sum('outstanding'))
        if due['n']:
            add(f"{_n(due['n'], 'فاتورة مورد يجب دفعها', 'فواتير موردين يجب دفعها')} هذا الأسبوع",
                reverse('accounting:payables'), 'عرض', 'warning', due['amt'])

        drafts = sum(
            qs.filter(status='draft').count()
            for qs in (Invoice.objects, Bill.objects, Payment.objects, CashAdvance.objects,
                       Expense.objects.filter(batch__isnull=True), ExpenseBatch.objects)
        )
        if drafts:
            add(f"{_n(drafts, 'مستند لم يُعتمد بعد', 'مستندات لم تُعتمد بعد')}",
                reverse('invoicing:list') + '?status=draft', 'راجع واعتمد', 'info')

        stale = CashAdvance.objects.filter(status='posted', date__lt=today - timedelta(days=30)).count()
        if stale:
            add(f"{_n(stale, 'موظف لم يُسوِّ سلفته', 'موظفين لم يسوّوا سلفهم')} منذ أكثر من شهر",
                reverse('advances:list') + '?status=posted', 'عرض', 'warning')

    if can_manage_scan_inbox(user):
        waiting = inbox_items().count()
        if waiting:
            add(f"{_n(waiting, 'ملف ممسوح ينتظر', 'ملفات ممسوحة تنتظر')} ربطه بمستند",
                reverse('core:scan_inbox'), 'اربط الآن', 'info')

    return items


def recent_documents(limit=6):
    """Latest activity, each row a short sentence ('دفعت لـ ...')."""
    from apps.advances.models import CashAdvance
    from apps.expenses.models import Expense
    from apps.invoicing.models import Bill, Invoice
    from apps.payments.models import Payment

    def payment_text(p):
        return f'استلام مبلغ من {p.partner.name}' if p.direction == 'inbound' else f'دفع مبلغ إلى {p.partner.name}'

    # (queryset, sentence, url name, money flow: 'in' = money coming to the company)
    sources = [
        (Invoice.objects.select_related('customer'), lambda d: f'فاتورة للزبون {d.customer.name}',
         'invoicing:detail', lambda d: 'in'),
        (Bill.objects.select_related('supplier'), lambda d: f'فاتورة من المورد {d.supplier.name}',
         'bills:detail', lambda d: 'out'),
        (Payment.objects.select_related('partner'), payment_text,
         'payments:detail', lambda d: 'in' if d.direction == 'inbound' else 'out'),
        (CashAdvance.objects.select_related('recipient'), lambda d: f'سلفة للموظف {d.recipient.name}',
         'advances:detail', lambda d: 'out'),
        (Expense.objects.all(), lambda d: f'مصروف: {d.description[:40]}',
         'expenses:detail', lambda d: 'out'),
    ]
    rows = []
    for qs, text, url_name, flow in sources:
        for doc in qs.order_by('-created_at')[:limit]:
            rows.append({
                'text': text(doc),
                'amount': doc.amount,
                'flow': flow(doc),
                'is_draft': doc.status == 'draft',
                'is_cancelled': doc.status == 'cancelled',
                'created_at': doc.created_at,
                'url': reverse(url_name, args=[doc.pk]),
            })
    rows.sort(key=lambda r: r['created_at'], reverse=True)
    return rows[:limit]


ARABIC_DAYS = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']


def arabic_date(d):
    """'الجمعة 2026/11/20' - month names differ by country, numbers don't."""
    return f'{ARABIC_DAYS[d.weekday()]} {d:%Y/%m/%d}'


def _currency_symbol():
    from apps.core.models import CompanySettings
    return CompanySettings.get_settings().currency_symbol


def greeting():
    hour = timezone.localtime().hour
    return 'صباح الخير' if hour < 12 else 'مساء الخير'


def build_dashboard(user):
    """Context for the dashboard. Financial figures only for report-capable roles."""
    from apps.accounts.permissions import can_view_reports
    from apps.invoicing.models import Bill, Invoice

    today = timezone.localdate()
    ctx = {
        'today': today,
        'today_text': arabic_date(today),
        'greeting': greeting(),
        'currency': _currency_symbol(),
        'show_financials': can_view_reports(user),
        'attention': attention_items(user, today),
        'recent': recent_documents(),
    }
    if ctx['show_financials']:
        ctx.update({
            'cash': cash_position(),
            'receivables': aging(Invoice.objects.all(), today),
            'payables': aging(Bill.objects.all(), today),
            'advances': open_advances(),
            'month': month_to_date(today),
            'projects': project_summary(),
        })
    return ctx
