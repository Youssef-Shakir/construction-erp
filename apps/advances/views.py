"""
Views for advances app.
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
from apps.core.models import Attachment
from .models import CashAdvance, AdvanceReturn
from .forms import CashAdvanceForm, AdvanceReturnForm


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
def advance_list(request):
    """List all cash advances."""
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    project_id = request.GET.get('project', '')

    advances = CashAdvance.objects.select_related(
        'project', 'recipient'
    ).order_by('-date', '-advance_number')

    if query:
        advances = advances.filter(
            Q(advance_number__icontains=query) |
            Q(recipient__name__icontains=query) |
            Q(project__name__icontains=query)
        )

    if status:
        advances = advances.filter(status=status)

    if project_id:
        advances = advances.filter(project_id=project_id)

    paginator = Paginator(advances, 25)
    page = request.GET.get('page', 1)
    advances = paginator.get_page(page)

    return render(request, 'advances/advance_list.html', {
        'advances': advances,
        'page_obj': advances,
        'query': query,
        'status': status,
        'project_id': project_id,
    })


@login_required
def advance_create(request):
    """Create a new cash advance."""
    if request.method == 'POST':
        form = CashAdvanceForm(request.POST)
        if form.is_valid():
            advance = form.save(commit=False)
            advance.amount_base = advance.amount
            advance.created_by = request.user
            advance.updated_by = request.user
            advance.save()

            # Handle file attachments
            _save_attachments(request, CashAdvance, advance.pk)

            messages.success(request, f'تم إنشاء السلفة {advance.advance_number}')
            return redirect('advances:detail', pk=advance.pk)
    else:
        form = CashAdvanceForm(initial={'date': timezone.now().date()})

    return render(request, 'advances/advance_form.html', {
        'form': form,
        'title': 'سلفة نقدية جديدة',
    })


@login_required
def advance_edit(request, pk):
    """Edit a draft advance."""
    advance = get_object_or_404(CashAdvance, pk=pk)

    if advance.status != 'draft':
        messages.error(request, 'لا يمكن تعديل سلفة مرحّلة')
        return redirect('advances:detail', pk=pk)

    if request.method == 'POST':
        form = CashAdvanceForm(request.POST, instance=advance)
        if form.is_valid():
            advance = form.save(commit=False)
            advance.amount_base = advance.amount
            advance.updated_by = request.user
            advance.save()
            messages.success(request, f'تم تحديث السلفة {advance.advance_number}')
            return redirect('advances:detail', pk=advance.pk)
    else:
        form = CashAdvanceForm(instance=advance)

    return render(request, 'advances/advance_form.html', {
        'form': form,
        'title': f'تعديل السلفة: {advance.advance_number}',
        'advance': advance,
    })


@login_required
def advance_detail(request, pk):
    """View advance details with settlement summary."""
    from django.contrib.contenttypes.models import ContentType
    from apps.core.models import Attachment

    advance = get_object_or_404(
        CashAdvance.objects.select_related('project', 'recipient', 'journal_entry'),
        pk=pk
    )

    # Get related expenses and returns
    from apps.expenses.models import Expense
    expenses = Expense.objects.filter(advance=advance).select_related('account')
    returns = advance.returns.all()

    # Get attachments
    content_type = ContentType.objects.get_for_model(CashAdvance)
    attachments = Attachment.objects.filter(
        content_type=content_type,
        object_id=advance.pk
    ).select_related('uploaded_by')

    # Get history records
    history_records = advance.history.all()[:50]

    return render(request, 'advances/advance_detail.html', {
        'advance': advance,
        'expenses': expenses,
        'returns': returns,
        'can_post': can_post_document(request.user),
        'content_type_id': content_type.pk,
        'object_id': advance.pk,
        'attachments': attachments,
        'history_records': history_records,
    })


@login_required
@posting_permission_required
def advance_post(request, pk):
    """Post a draft advance."""
    advance = get_object_or_404(CashAdvance, pk=pk)

    if request.method == 'POST':
        try:
            advance.post(user=request.user)
            messages.success(request, f'تم ترحيل السلفة {advance.advance_number}')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('advances:detail', pk=pk)


@login_required
@posting_permission_required
def advance_cancel(request, pk):
    """Cancel a posted advance."""
    advance = get_object_or_404(CashAdvance, pk=pk)

    if request.method == 'POST':
        try:
            advance.cancel(user=request.user)
            messages.success(request, f'تم إلغاء السلفة {advance.advance_number}')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('advances:detail', pk=pk)


@login_required
@posting_permission_required
def advance_close(request, pk):
    """Close a fully settled advance."""
    advance = get_object_or_404(CashAdvance, pk=pk)

    if request.method == 'POST':
        try:
            advance.close()
            messages.success(request, f'تم إغلاق السلفة {advance.advance_number}')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('advances:detail', pk=pk)


# Advance Return views
@login_required
def return_create(request, advance_pk=None):
    """Create a new advance return."""
    initial = {}
    if advance_pk:
        advance = get_object_or_404(CashAdvance, pk=advance_pk)
        initial['advance'] = advance
        initial['amount'] = advance.remaining

    if request.method == 'POST':
        form = AdvanceReturnForm(request.POST)
        if form.is_valid():
            ret = form.save(commit=False)
            ret.amount_base = ret.amount
            ret.created_by = request.user
            ret.updated_by = request.user
            ret.save()
            messages.success(request, f'تم إنشاء مردود السلفة {ret.return_number}')
            return redirect('advances:detail', pk=ret.advance.pk)
    else:
        form = AdvanceReturnForm(initial=initial)
        if advance_pk:
            initial['date'] = timezone.now().date()
            form = AdvanceReturnForm(initial=initial)

    return render(request, 'advances/return_form.html', {
        'form': form,
        'title': 'مردود سلفة جديد',
    })


@login_required
@posting_permission_required
def return_post(request, pk):
    """Post a draft return."""
    ret = get_object_or_404(AdvanceReturn, pk=pk)

    if request.method == 'POST':
        try:
            ret.post(user=request.user)
            messages.success(request, f'تم ترحيل مردود السلفة {ret.return_number}')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('advances:detail', pk=ret.advance.pk)
