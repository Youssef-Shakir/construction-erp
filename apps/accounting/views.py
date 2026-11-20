"""
Views for accounting app.
"""
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.utils import timezone

from apps.accounts.permissions import (
    business_manager_required,
    accountant_required,
    can_create_reversal,
)
from .models import Account, AccountType, Journal, JournalEntry, JournalLine
from .forms import (
    AccountForm,
    JournalForm,
    JournalEntryForm,
    JournalLineFormSet,
    LedgerFilterForm,
    TrialBalanceFilterForm,
)
from .posting import create_journal_entry, reverse_entry, get_trial_balance, get_income_statement, PostingError


# Chart of Accounts Views
@login_required
@business_manager_required
def account_list(request):
    """List all accounts (chart of accounts)."""
    accounts = Account.objects.select_related(
        'account_type', 'parent'
    ).order_by('code')

    # Group by account type for display
    account_types = AccountType.objects.prefetch_related('accounts').order_by('order')

    return render(request, 'accounting/account_list.html', {
        'accounts': accounts,
        'account_types': account_types,
    })


@login_required
@business_manager_required
def account_create(request):
    """Create a new account."""
    if request.method == 'POST':
        form = AccountForm(request.POST)
        if form.is_valid():
            account = form.save()
            messages.success(request, f'تم إنشاء الحساب {account.name} بنجاح')
            return redirect('accounting:accounts')
    else:
        form = AccountForm()

    return render(request, 'accounting/account_form.html', {
        'form': form,
        'title': 'إضافة حساب جديد',
    })


@login_required
@business_manager_required
def account_edit(request, pk):
    """Edit an existing account."""
    account = get_object_or_404(Account, pk=pk)

    if request.method == 'POST':
        form = AccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, f'تم تحديث الحساب {account.name} بنجاح')
            return redirect('accounting:accounts')
    else:
        form = AccountForm(instance=account)

    return render(request, 'accounting/account_form.html', {
        'form': form,
        'title': f'تعديل الحساب: {account.name}',
        'account': account,
    })


# Journal Views
@login_required
@business_manager_required
def journal_list(request):
    """List all journals."""
    journals = Journal.objects.all().order_by('code')
    return render(request, 'accounting/journal_list.html', {
        'journals': journals,
    })


@login_required
@business_manager_required
def journal_create(request):
    """Create a new journal."""
    if request.method == 'POST':
        form = JournalForm(request.POST)
        if form.is_valid():
            journal = form.save()
            messages.success(request, f'تم إنشاء اليومية {journal.name} بنجاح')
            return redirect('accounting:journals')
    else:
        form = JournalForm()

    return render(request, 'accounting/journal_form.html', {
        'form': form,
        'title': 'إضافة يومية جديدة',
    })


@login_required
@business_manager_required
def journal_edit(request, pk):
    """Edit an existing journal."""
    journal = get_object_or_404(Journal, pk=pk)

    if request.method == 'POST':
        form = JournalForm(request.POST, instance=journal)
        if form.is_valid():
            form.save()
            messages.success(request, f'تم تحديث اليومية {journal.name} بنجاح')
            return redirect('accounting:journals')
    else:
        form = JournalForm(instance=journal)

    return render(request, 'accounting/journal_form.html', {
        'form': form,
        'title': f'تعديل اليومية: {journal.name}',
        'journal': journal,
    })


# Journal Entry Views
@login_required
@accountant_required
def entry_list(request):
    """List all journal entries."""
    query = request.GET.get('q', '')
    journal_id = request.GET.get('journal', '')
    status = request.GET.get('status', '')

    entries = JournalEntry.objects.select_related(
        'journal', 'posted_by'
    ).prefetch_related('lines').order_by('-date', '-entry_number')

    if query:
        entries = entries.filter(
            Q(entry_number__icontains=query) |
            Q(reference__icontains=query) |
            Q(memo__icontains=query)
        )

    if journal_id:
        entries = entries.filter(journal_id=journal_id)

    if status == 'posted':
        entries = entries.filter(is_posted=True, is_reversed=False)
    elif status == 'reversed':
        entries = entries.filter(is_reversed=True)
    elif status == 'draft':
        entries = entries.filter(is_posted=False)

    # Pagination
    paginator = Paginator(entries, 25)
    page = request.GET.get('page', 1)
    entries = paginator.get_page(page)

    journals = Journal.objects.filter(is_active=True)

    return render(request, 'accounting/entry_list.html', {
        'entries': entries,
        'page_obj': entries,
        'query': query,
        'journal_id': journal_id,
        'status': status,
        'journals': journals,
    })


@login_required
@accountant_required
def entry_create(request):
    """Create a manual journal entry."""
    if request.method == 'POST':
        form = JournalEntryForm(request.POST)
        formset = JournalLineFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            # Build lines for posting
            lines = []
            for line_form in formset:
                if line_form.cleaned_data and not line_form.cleaned_data.get('DELETE'):
                    account = line_form.cleaned_data.get('account')
                    if account:
                        lines.append({
                            'account': account,
                            'debit': line_form.cleaned_data.get('debit') or Decimal('0.00'),
                            'credit': line_form.cleaned_data.get('credit') or Decimal('0.00'),
                            'description': line_form.cleaned_data.get('description', ''),
                            'partner': line_form.cleaned_data.get('partner'),
                            'project': line_form.cleaned_data.get('project'),
                        })

            try:
                entry = create_journal_entry(
                    journal=form.cleaned_data['journal'],
                    date=form.cleaned_data['date'],
                    lines=lines,
                    memo=form.cleaned_data.get('memo', ''),
                    user=request.user,
                    auto_post=True,
                )
                messages.success(request, f'تم إنشاء القيد {entry.entry_number} بنجاح')
                return redirect('accounting:entry_detail', pk=entry.pk)
            except PostingError as e:
                messages.error(request, str(e))
    else:
        form = JournalEntryForm(initial={'date': timezone.now().date()})
        formset = JournalLineFormSet()

    return render(request, 'accounting/entry_form.html', {
        'form': form,
        'formset': formset,
        'title': 'قيد يومية جديد',
    })


@login_required
@accountant_required
def entry_detail(request, pk):
    """View journal entry details."""
    entry = get_object_or_404(
        JournalEntry.objects.select_related('journal', 'posted_by', 'created_by')
        .prefetch_related('lines__account', 'lines__partner', 'lines__project'),
        pk=pk
    )

    return render(request, 'accounting/entry_detail.html', {
        'entry': entry,
    })


@login_required
@business_manager_required
def entry_reverse(request, pk):
    """Reverse a posted journal entry."""
    entry = get_object_or_404(JournalEntry, pk=pk)

    if not can_create_reversal(request.user):
        messages.error(request, 'ليس لديك صلاحية لإلغاء القيود')
        return redirect('accounting:entry_detail', pk=pk)

    if request.method == 'POST':
        try:
            reversal = reverse_entry(
                entry=entry,
                date=timezone.now().date(),
                user=request.user,
            )
            messages.success(request, f'تم إلغاء القيد. قيد الإلغاء: {reversal.entry_number}')
            return redirect('accounting:entry_detail', pk=reversal.pk)
        except PostingError as e:
            messages.error(request, str(e))

    return render(request, 'accounting/entry_reverse_confirm.html', {
        'entry': entry,
    })


# Ledger View
@login_required
@accountant_required
def ledger(request):
    """General ledger view for an account."""
    form = LedgerFilterForm(request.GET or None)
    lines = []
    account = None
    running_balance = Decimal('0.00')

    if form.is_valid():
        account = form.cleaned_data['account']
        date_from = form.cleaned_data.get('date_from')
        date_to = form.cleaned_data.get('date_to')

        query = Q(account=account, entry__is_posted=True)

        if date_from:
            query &= Q(entry__date__gte=date_from)
        if date_to:
            query &= Q(entry__date__lte=date_to)

        lines = JournalLine.objects.filter(query).select_related(
            'entry', 'entry__journal', 'partner', 'project'
        ).order_by('entry__date', 'entry__entry_number', 'line_number')

        # Calculate opening balance if date_from specified
        if date_from:
            opening = account.get_balance_at_date(date_from)
            running_balance = opening

    return render(request, 'accounting/ledger.html', {
        'form': form,
        'account': account,
        'lines': lines,
        'running_balance': running_balance,
    })


# Trial Balance
@login_required
@accountant_required
def trial_balance(request):
    """Trial balance report."""
    form = TrialBalanceFilterForm(request.GET or None)
    as_of_date = None

    if form.is_valid():
        as_of_date = form.cleaned_data.get('as_of_date')

    data = get_trial_balance(as_of_date)

    return render(request, 'accounting/trial_balance.html', {
        'form': form,
        'data': data,
        'as_of_date': as_of_date,
    })


# Financial Reports
@login_required
@accountant_required
def income_statement(request):
    """Income statement (profit and loss) report - company-wide, or scoped to one project."""
    from apps.projects.models import Project

    form = TrialBalanceFilterForm(request.GET or None)
    as_of_date = timezone.now().date()

    if form.is_valid() and form.cleaned_data.get('as_of_date'):
        as_of_date = form.cleaned_data['as_of_date']

    project = None
    project_id = request.GET.get('project', '')
    if project_id.isdigit():
        project = Project.objects.filter(pk=project_id).first()

    data = get_income_statement(as_of_date, project=project)

    return render(request, 'accounting/income_statement.html', {
        'form': form,
        'as_of_date': as_of_date,
        'revenue_data': data['revenue_data'],
        'expense_data': data['expense_data'],
        'total_revenue': data['total_revenue'],
        'total_expenses': data['total_expenses'],
        'net_income': data['net_income'],
        'projects': Project.objects.order_by('code'),
        'project_id': project_id,
        'selected_project': project,
    })


@login_required
@accountant_required
def balance_sheet(request):
    """Balance sheet report."""
    form = TrialBalanceFilterForm(request.GET or None)
    as_of_date = timezone.now().date()

    if form.is_valid() and form.cleaned_data.get('as_of_date'):
        as_of_date = form.cleaned_data['as_of_date']

    # Get accounts by type
    asset_accounts = Account.objects.filter(
        account_type__code='asset',
        is_active=True
    ).select_related('account_type')

    liability_accounts = Account.objects.filter(
        account_type__code='liability',
        is_active=True
    ).select_related('account_type')

    equity_accounts = Account.objects.filter(
        account_type__code='equity',
        is_active=True
    ).select_related('account_type')

    # Calculate balances
    def get_balances(accounts):
        data = []
        total = Decimal('0.00')
        for acc in accounts:
            balance = acc.get_balance_at_date(as_of_date) if as_of_date else acc.balance
            if balance != 0:
                data.append({'account': acc, 'balance': abs(balance)})
                total += abs(balance)
        return data, total

    asset_data, total_assets = get_balances(asset_accounts)
    liability_data, total_liabilities = get_balances(liability_accounts)
    equity_data, total_equity = get_balances(equity_accounts)

    # Calculate retained earnings (revenue - expenses)
    revenue_accounts = Account.objects.filter(account_type__code='revenue', is_active=True)
    expense_accounts = Account.objects.filter(account_type__code='expense', is_active=True)

    total_revenue = Decimal('0.00')
    for acc in revenue_accounts:
        balance = acc.get_balance_at_date(as_of_date) if as_of_date else acc.balance
        total_revenue += abs(balance)

    total_expenses = Decimal('0.00')
    for acc in expense_accounts:
        balance = acc.get_balance_at_date(as_of_date) if as_of_date else acc.balance
        total_expenses += abs(balance)

    retained_earnings = total_revenue - total_expenses
    total_equity_with_retained = total_equity + retained_earnings

    return render(request, 'accounting/balance_sheet.html', {
        'form': form,
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
    })


# Receivables and Payables
@login_required
@accountant_required
def receivables(request):
    """Accounts receivable report (outstanding invoices)."""
    from apps.invoicing.models import Invoice

    invoices = Invoice.objects.filter(
        status='posted'
    ).select_related('customer', 'project').order_by('due_date')

    # Filter out fully paid
    outstanding = []
    total_outstanding = Decimal('0.00')
    total_overdue = Decimal('0.00')

    for inv in invoices:
        if inv.amount_remaining > 0:
            outstanding.append({
                'invoice': inv,
                'remaining': inv.amount_remaining,
                'is_overdue': inv.is_overdue,
            })
            total_outstanding += inv.amount_remaining
            if inv.is_overdue:
                total_overdue += inv.amount_remaining

    return render(request, 'accounting/receivables.html', {
        'outstanding': outstanding,
        'total_outstanding': total_outstanding,
        'total_overdue': total_overdue,
    })


@login_required
@accountant_required
def payables(request):
    """Accounts payable report (outstanding bills)."""
    from apps.invoicing.models import Bill

    bills = Bill.objects.filter(
        status='posted'
    ).select_related('supplier', 'project').order_by('due_date')

    # Filter out fully paid
    outstanding = []
    total_outstanding = Decimal('0.00')
    total_overdue = Decimal('0.00')

    for bill in bills:
        if bill.amount_remaining > 0:
            outstanding.append({
                'bill': bill,
                'remaining': bill.amount_remaining,
                'is_overdue': bill.is_overdue,
            })
            total_outstanding += bill.amount_remaining
            if bill.is_overdue:
                total_overdue += bill.amount_remaining

    return render(request, 'accounting/payables.html', {
        'outstanding': outstanding,
        'total_outstanding': total_outstanding,
        'total_overdue': total_overdue,
    })
