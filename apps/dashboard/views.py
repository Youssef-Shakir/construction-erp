"""
Dashboard views.
"""
from decimal import Decimal
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta


@login_required
def dashboard(request):
    """Main dashboard view with summary statistics."""
    from apps.projects.models import Project
    from apps.invoicing.models import Invoice, Bill
    from apps.advances.models import CashAdvance
    from apps.expenses.models import Expense
    from apps.payments.models import Payment

    today = timezone.now().date()

    # Active projects
    active_projects = Project.objects.filter(status='active').count()

    # Outstanding receivables
    invoices = Invoice.objects.filter(status='posted')
    total_receivables = Decimal('0.00')
    overdue_receivables = Decimal('0.00')
    for inv in invoices:
        remaining = inv.amount_remaining
        if remaining > 0:
            total_receivables += remaining
            if inv.is_overdue:
                overdue_receivables += remaining

    # Outstanding payables
    bills = Bill.objects.filter(status='posted')
    total_payables = Decimal('0.00')
    overdue_payables = Decimal('0.00')
    for bill in bills:
        remaining = bill.amount_remaining
        if remaining > 0:
            total_payables += remaining
            if bill.is_overdue:
                overdue_payables += remaining

    # Open advances
    open_advances = CashAdvance.objects.filter(status='posted')
    total_open_advances = Decimal('0.00')
    for adv in open_advances:
        total_open_advances += adv.remaining

    # Recent activity
    recent_invoices = Invoice.objects.select_related('customer', 'project').order_by('-created_at')[:5]
    recent_bills = Bill.objects.select_related('supplier', 'project').order_by('-created_at')[:5]
    recent_payments = Payment.objects.select_related('partner', 'account').order_by('-created_at')[:5]
    recent_advances = CashAdvance.objects.select_related('recipient', 'project').order_by('-created_at')[:5]
    recent_expenses = Expense.objects.select_related('account', 'project').order_by('-created_at')[:5]
    recent_projects = Project.objects.select_related('customer').order_by('-created_at')[:5]

    # Summary stats
    this_month_start = today.replace(day=1)
    monthly_revenue = Invoice.objects.filter(
        status='posted',
        date__gte=this_month_start
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    monthly_expenses = Expense.objects.filter(
        status='posted',
        date__gte=this_month_start
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    monthly_bills = Bill.objects.filter(
        status='posted',
        date__gte=this_month_start
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    context = {
        'active_projects': active_projects,
        'total_receivables': total_receivables,
        'overdue_receivables': overdue_receivables,
        'total_payables': total_payables,
        'overdue_payables': overdue_payables,
        'total_open_advances': total_open_advances,
        'recent_invoices': recent_invoices,
        'recent_bills': recent_bills,
        'recent_payments': recent_payments,
        'recent_advances': recent_advances,
        'recent_expenses': recent_expenses,
        'recent_projects': recent_projects,
        'monthly_revenue': monthly_revenue,
        'monthly_expenses': monthly_expenses,
        'monthly_bills': monthly_bills,
    }

    return render(request, 'dashboard/dashboard.html', context)
