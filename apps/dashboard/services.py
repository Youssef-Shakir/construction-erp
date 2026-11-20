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


def attention_items(user, today):
    """Work queue: what someone should act on now."""
    from apps.accounts.permissions import can_manage_scan_inbox, can_post_document
    from apps.advances.models import CashAdvance
    from apps.core.attachments import inbox_items
    from apps.expenses.models import Expense, ExpenseBatch
    from apps.invoicing.models import Bill, Invoice
    from apps.payments.models import Payment

    items = []

    def add(label, count, url, level='info', amount=None):
        if count:
            items.append({'label': label, 'count': count, 'amount': amount, 'url': url, 'level': level})

    if can_post_document(user):
        drafts = [
            ('فواتير عملاء بانتظار الترحيل', Invoice.objects, 'invoicing:list'),
            ('فواتير موردين بانتظار الترحيل', Bill.objects, 'bills:list'),
            ('مدفوعات بانتظار الترحيل', Payment.objects, 'payments:list'),
            ('سلف بانتظار الترحيل', CashAdvance.objects, 'advances:list'),
            ('مصروفات بانتظار الترحيل', Expense.objects.filter(batch__isnull=True), 'expenses:list'),
        ]
        for label, qs, url_name in drafts:
            agg = qs.filter(status='draft').aggregate(n=Count('pk'), amt=Sum('amount'))
            add(label, agg['n'], reverse(url_name) + '?status=draft', 'info', agg['amt'])
        add('مستندات مصاريف بانتظار الترحيل', ExpenseBatch.objects.filter(status='draft').count(),
            reverse('advances:list'), 'info')

        overdue = with_outstanding(Invoice.objects.filter(due_date__lt=today)).aggregate(
            n=Count('pk'), amt=Sum('outstanding'))
        add('فواتير عملاء متأخرة السداد', overdue['n'], reverse('accounting:receivables'), 'danger', overdue['amt'])

        due = with_outstanding(Bill.objects.filter(due_date__lte=today + timedelta(days=7))).aggregate(
            n=Count('pk'), amt=Sum('outstanding'))
        add('فواتير موردين مستحقة خلال 7 أيام', due['n'], reverse('accounting:payables'), 'warning', due['amt'])

        stale = CashAdvance.objects.filter(status='posted', date__lt=today - timedelta(days=30)).count()
        add('سلف مفتوحة منذ أكثر من 30 يوماً', stale, reverse('advances:list') + '?status=posted', 'warning')

    if can_manage_scan_inbox(user):
        add('ملفات في صندوق المسح بانتظار الربط', inbox_items().count(), reverse('core:scan_inbox'), 'info')

    return items


def recent_documents(limit=10):
    """Latest documents of every type, merged and sorted by creation time."""
    from apps.advances.models import CashAdvance
    from apps.expenses.models import Expense
    from apps.invoicing.models import Bill, Invoice
    from apps.payments.models import Payment

    sources = [
        (Invoice.objects.select_related('customer'), 'فاتورة', 'invoice_number', 'customer', 'invoicing:detail'),
        (Bill.objects.select_related('supplier'), 'فاتورة مورد', 'bill_number', 'supplier', 'bills:detail'),
        (Payment.objects.select_related('partner'), 'دفعة', 'payment_number', 'partner', 'payments:detail'),
        (CashAdvance.objects.select_related('recipient'), 'سلفة', 'advance_number', 'recipient', 'advances:detail'),
        (Expense.objects.select_related('partner'), 'مصروف', 'expense_number', 'partner', 'expenses:detail'),
    ]
    rows = []
    for qs, label, number_field, party_field, url_name in sources:
        for doc in qs.order_by('-created_at')[:limit]:
            party = getattr(doc, party_field)
            rows.append({
                'type': label,
                'number': getattr(doc, number_field),
                'party': party.name if party else (getattr(doc, 'description', '') or '')[:40],
                'date': doc.date,
                'amount': doc.amount,
                'status': doc.status,
                'status_label': doc.get_status_display(),
                'created_at': doc.created_at,
                'url': reverse(url_name, args=[doc.pk]),
            })
    rows.sort(key=lambda r: r['created_at'], reverse=True)
    return rows[:limit]


def build_dashboard(user):
    """Context for the dashboard. Financial figures only for report-capable roles."""
    from apps.accounts.permissions import can_view_reports
    from apps.invoicing.models import Bill, Invoice

    today = timezone.localdate()
    ctx = {
        'today': today,
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
