"""
Views for expenses app.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.core.paginator import Paginator
from django.utils import timezone

from apps.accounts.permissions import can_post_document, posting_permission_required
from apps.accounting.posting import PostingError
from apps.advances.models import CashAdvance
from apps.core.models import Attachment
from .models import Expense, ExpenseBatch, PaperReceipt
from .forms import ExpenseForm, PaperReceiptForm


def _save_attachments(request, model_class, object_id):
    """Save uploaded attachments to a model instance."""
    files = request.FILES.getlist('attachments')
    if files:
        content_type = ContentType.objects.get_for_model(model_class)
        for f in files:
            Attachment.objects.create(
                content_type=content_type,
                object_id=object_id,
                file=f,
                original_filename=f.name,
                uploaded_by=request.user,
            )


@login_required
def expense_list(request):
    """List all expenses."""
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    expense_type = request.GET.get('type', '')
    project_id = request.GET.get('project', '')

    expenses = Expense.objects.select_related(
        'project', 'advance', 'account', 'partner'
    ).order_by('-date', '-expense_number')

    if query:
        expenses = expenses.filter(
            Q(expense_number__icontains=query) |
            Q(description__icontains=query)
        )

    if status:
        expenses = expenses.filter(status=status)

    if expense_type == 'advance':
        expenses = expenses.filter(advance__isnull=False)
    elif expense_type == 'project':
        expenses = expenses.filter(advance__isnull=True, project__isnull=False)
    elif expense_type == 'company':
        expenses = expenses.filter(advance__isnull=True, project__isnull=True)

    if project_id:
        expenses = expenses.filter(project_id=project_id)

    paginator = Paginator(expenses, 25)
    page = request.GET.get('page', 1)
    expenses = paginator.get_page(page)

    return render(request, 'expenses/expense_list.html', {
        'expenses': expenses,
        'page_obj': expenses,
        'query': query,
        'status': status,
        'expense_type': expense_type,
        'project_id': project_id,
    })


@login_required
def expense_create(request):
    """Create a new expense."""
    initial = {'date': timezone.now().date()}

    # Pre-fill from advance if provided
    advance_pk = request.GET.get('advance')
    if advance_pk:
        advance = get_object_or_404(CashAdvance, pk=advance_pk)
        initial['advance'] = advance
        initial['project'] = advance.project

    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.amount_base = expense.amount
            # Inherit project from advance if not specified
            if expense.advance and not expense.project:
                expense.project = expense.advance.project
            expense.created_by = request.user
            expense.updated_by = request.user
            expense.save()

            # Handle file attachments
            _save_attachments(request, Expense, expense.pk)

            messages.success(request, f'تم إنشاء المصروف {expense.expense_number}')
            return redirect('expenses:detail', pk=expense.pk)
    else:
        form = ExpenseForm(initial=initial)

    return render(request, 'expenses/expense_form.html', {
        'form': form,
        'title': 'مصروف جديد',
    })


@login_required
def expense_edit(request, pk):
    """Edit a draft expense."""
    expense = get_object_or_404(Expense, pk=pk)

    if expense.status != 'draft':
        messages.error(request, 'لا يمكن تعديل مصروف مرحّل')
        return redirect('expenses:detail', pk=pk)

    if request.method == 'POST':
        form = ExpenseForm(request.POST, instance=expense)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.amount_base = expense.amount
            if expense.advance and not expense.project:
                expense.project = expense.advance.project
            expense.updated_by = request.user
            expense.save()
            messages.success(request, f'تم تحديث المصروف {expense.expense_number}')
            return redirect('expenses:detail', pk=expense.pk)
    else:
        form = ExpenseForm(instance=expense)

    return render(request, 'expenses/expense_form.html', {
        'form': form,
        'title': f'تعديل المصروف: {expense.expense_number}',
        'expense': expense,
    })


@login_required
def expense_detail(request, pk):
    """View expense details."""
    from django.contrib.contenttypes.models import ContentType
    from apps.core.models import Attachment

    expense = get_object_or_404(
        Expense.objects.select_related(
            'project', 'advance', 'account', 'partner', 'journal_entry'
        ),
        pk=pk
    )

    # Get attachments
    content_type = ContentType.objects.get_for_model(Expense)
    attachments = Attachment.objects.filter(
        content_type=content_type,
        object_id=expense.pk
    ).select_related('uploaded_by')

    # Get history records
    history_records = expense.history.all()[:50]

    return render(request, 'expenses/expense_detail.html', {
        'expense': expense,
        'can_post': can_post_document(request.user),
        'content_type_id': content_type.pk,
        'object_id': expense.pk,
        'attachments': attachments,
        'history_records': history_records,
    })


@login_required
@posting_permission_required
def expense_post(request, pk):
    """Post a draft expense."""
    expense = get_object_or_404(Expense, pk=pk)

    if request.method == 'POST':
        try:
            expense.post(user=request.user)
            messages.success(request, f'تم ترحيل المصروف {expense.expense_number}')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('expenses:detail', pk=pk)


@login_required
@posting_permission_required
def expense_cancel(request, pk):
    """Cancel a posted expense."""
    expense = get_object_or_404(Expense, pk=pk)

    if request.method == 'POST':
        try:
            expense.cancel(user=request.user)
            messages.success(request, f'تم إلغاء المصروف {expense.expense_number}')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('expenses:detail', pk=pk)


# Expense Batch views ("مستند مصاريف" - bulk expense lines against an advance)
@login_required
def batch_detail(request, pk):
    """View an expense-lines document: its lines, shared journal entry, attachments."""
    batch = get_object_or_404(
        ExpenseBatch.objects.select_related('advance', 'advance__recipient', 'advance__project', 'journal_entry'),
        pk=pk
    )
    lines = batch.lines.select_related('project', 'account').order_by('id')

    content_type = ContentType.objects.get_for_model(ExpenseBatch)
    attachments = Attachment.objects.filter(
        content_type=content_type,
        object_id=batch.pk
    ).select_related('uploaded_by')

    history_records = batch.history.all()[:50]

    return render(request, 'expenses/batch_detail.html', {
        'batch': batch,
        'lines': lines,
        'can_post': can_post_document(request.user),
        'content_type_id': content_type.pk,
        'object_id': batch.pk,
        'attachments': attachments,
        'history_records': history_records,
    })


@login_required
@posting_permission_required
def batch_post(request, pk):
    """Post an expense-lines document - creates ONE journal entry for all its lines."""
    batch = get_object_or_404(ExpenseBatch, pk=pk)

    if request.method == 'POST':
        try:
            batch.post(user=request.user)
            messages.success(request, f'تم ترحيل مستند المصاريف {batch.batch_number} بقيد واحد')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('expenses:batch_detail', pk=pk)


@login_required
@posting_permission_required
def batch_cancel(request, pk):
    """Cancel a posted expense-lines document by reversing its single entry."""
    batch = get_object_or_404(ExpenseBatch, pk=pk)

    if request.method == 'POST':
        try:
            batch.cancel(user=request.user)
            messages.success(request, f'تم إلغاء مستند المصاريف {batch.batch_number}')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('expenses:batch_detail', pk=pk)


# Paper Receipt views
@login_required
def receipt_list(request):
    """List all paper receipts."""
    query = request.GET.get('q', '')
    matched = request.GET.get('matched', '')

    receipts = PaperReceipt.objects.select_related(
        'expense', 'received_from'
    ).order_by('-date')

    if query:
        receipts = receipts.filter(
            Q(receipt_number__icontains=query) |
            Q(vendor_name__icontains=query)
        )

    if matched == 'yes':
        receipts = receipts.filter(matched=True)
    elif matched == 'no':
        receipts = receipts.filter(matched=False)

    paginator = Paginator(receipts, 25)
    page = request.GET.get('page', 1)
    receipts = paginator.get_page(page)

    return render(request, 'expenses/receipt_list.html', {
        'receipts': receipts,
        'page_obj': receipts,
        'query': query,
        'matched': matched,
    })


@login_required
def receipt_create(request):
    """Create a new paper receipt."""
    if request.method == 'POST':
        form = PaperReceiptForm(request.POST)
        if form.is_valid():
            receipt = form.save()
            messages.success(request, f'تم تسجيل الإيصال {receipt.receipt_number}')
            return redirect('expenses:receipts')
    else:
        form = PaperReceiptForm(initial={'date': timezone.now().date()})

    return render(request, 'expenses/receipt_form.html', {
        'form': form,
        'title': 'تسجيل إيصال ورقي',
    })
