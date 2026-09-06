"""
Views for payments app.
"""
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from apps.accounts.permissions import can_post_document, posting_permission_required
from apps.accounting.posting import PostingError
from apps.core.models import Attachment
from apps.invoicing.models import Invoice, Bill
from .models import Payment, PaymentAllocation
from .forms import PaymentForm


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
def payment_list(request):
    """List all payments."""
    query = request.GET.get('q', '')
    direction = request.GET.get('direction', '')
    status = request.GET.get('status', '')

    payments = Payment.objects.select_related(
        'partner', 'account'
    ).order_by('-date', '-payment_number')

    if query:
        payments = payments.filter(
            Q(payment_number__icontains=query) |
            Q(partner__name__icontains=query) |
            Q(reference__icontains=query)
        )

    if direction:
        payments = payments.filter(direction=direction)

    if status:
        payments = payments.filter(status=status)

    paginator = Paginator(payments, 25)
    page = request.GET.get('page', 1)
    payments = paginator.get_page(page)

    return render(request, 'payments/payment_list.html', {
        'payments': payments,
        'page_obj': payments,
        'query': query,
        'direction': direction,
        'status': status,
    })


@login_required
def payment_create(request, direction='inbound'):
    """Create a new payment."""
    if request.method == 'POST':
        form = PaymentForm(request.POST, direction=direction)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.amount_base = payment.amount
            payment.created_by = request.user
            payment.updated_by = request.user
            payment.save()

            # Handle file attachments
            _save_attachments(request, Payment, payment.pk)

            messages.success(request, f'تم إنشاء الدفعة {payment.payment_number}')
            return redirect('payments:detail', pk=payment.pk)
    else:
        form = PaymentForm(
            initial={'date': timezone.now().date(), 'direction': direction},
            direction=direction
        )

    title = 'استلام دفعة' if direction == 'inbound' else 'صرف دفعة'

    return render(request, 'payments/payment_form.html', {
        'form': form,
        'title': title,
        'direction': direction,
    })


@login_required
def payment_edit(request, pk):
    """Edit a draft payment."""
    payment = get_object_or_404(Payment, pk=pk)

    if payment.status != 'draft':
        messages.error(request, 'لا يمكن تعديل دفعة مرحّلة')
        return redirect('payments:detail', pk=pk)

    if request.method == 'POST':
        form = PaymentForm(request.POST, instance=payment, direction=payment.direction)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.amount_base = payment.amount
            payment.updated_by = request.user
            payment.save()
            messages.success(request, f'تم تحديث الدفعة {payment.payment_number}')
            return redirect('payments:detail', pk=payment.pk)
    else:
        form = PaymentForm(instance=payment, direction=payment.direction)

    title = 'تعديل استلام دفعة' if payment.direction == 'inbound' else 'تعديل صرف دفعة'

    return render(request, 'payments/payment_form.html', {
        'form': form,
        'title': title,
        'payment': payment,
        'direction': payment.direction,
    })


@login_required
def payment_detail(request, pk):
    """View payment details with allocations."""
    from apps.core.models import Attachment

    payment = get_object_or_404(
        Payment.objects.select_related('partner', 'account', 'journal_entry'),
        pk=pk
    )

    allocations = payment.allocations.all()

    # Get available documents for allocation
    available_docs = []
    if payment.status == 'posted' and payment.unallocated_amount > 0:
        if payment.direction == 'inbound':
            # Get unpaid invoices from this customer
            docs = Invoice.objects.filter(
                customer=payment.partner,
                status='posted'
            )
            for doc in docs:
                if doc.amount_remaining > 0:
                    available_docs.append({
                        'type': 'invoice',
                        'doc': doc,
                        'remaining': doc.amount_remaining,
                    })
        else:
            # Get unpaid bills to this supplier
            docs = Bill.objects.filter(
                supplier=payment.partner,
                status='posted'
            )
            for doc in docs:
                if doc.amount_remaining > 0:
                    available_docs.append({
                        'type': 'bill',
                        'doc': doc,
                        'remaining': doc.amount_remaining,
                    })

    # Get attachments
    content_type = ContentType.objects.get_for_model(Payment)
    attachments = Attachment.objects.filter(
        content_type=content_type,
        object_id=payment.pk
    ).select_related('uploaded_by')

    # Get history records
    history_records = payment.history.all()[:50]

    return render(request, 'payments/payment_detail.html', {
        'payment': payment,
        'allocations': allocations,
        'available_docs': available_docs,
        'can_post': can_post_document(request.user),
        'content_type_id': content_type.pk,
        'object_id': payment.pk,
        'attachments': attachments,
        'history_records': history_records,
    })


@login_required
@posting_permission_required
def payment_post(request, pk):
    """Post a draft payment."""
    payment = get_object_or_404(Payment, pk=pk)

    if request.method == 'POST':
        try:
            payment.post(user=request.user)
            messages.success(request, f'تم ترحيل الدفعة {payment.payment_number}')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('payments:detail', pk=pk)


@login_required
@posting_permission_required
def payment_cancel(request, pk):
    """Cancel a posted payment."""
    payment = get_object_or_404(Payment, pk=pk)

    if request.method == 'POST':
        try:
            payment.cancel(user=request.user)
            messages.success(request, f'تم إلغاء الدفعة {payment.payment_number}')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('payments:detail', pk=pk)


@login_required
@posting_permission_required
def payment_allocate(request, pk):
    """Allocate payment to an invoice or bill."""
    payment = get_object_or_404(Payment, pk=pk)

    if payment.status != 'posted':
        messages.error(request, 'يجب ترحيل الدفعة أولاً')
        return redirect('payments:detail', pk=pk)

    if request.method == 'POST':
        doc_type = request.POST.get('doc_type')
        doc_id = request.POST.get('doc_id')
        amount = request.POST.get('amount')

        try:
            amount = Decimal(amount)
        except (ValueError, TypeError):
            messages.error(request, 'المبلغ غير صالح')
            return redirect('payments:detail', pk=pk)

        if amount <= 0:
            messages.error(request, 'المبلغ يجب أن يكون أكبر من صفر')
            return redirect('payments:detail', pk=pk)

        if amount > payment.unallocated_amount:
            messages.error(request, f'المبلغ يتجاوز المتبقي ({payment.unallocated_amount})')
            return redirect('payments:detail', pk=pk)

        # Get the document
        if doc_type == 'invoice':
            doc = get_object_or_404(Invoice, pk=doc_id)
            ct = ContentType.objects.get_for_model(Invoice)
        else:
            doc = get_object_or_404(Bill, pk=doc_id)
            ct = ContentType.objects.get_for_model(Bill)

        if amount > doc.amount_remaining:
            messages.error(request, f'المبلغ يتجاوز المتبقي في المستند ({doc.amount_remaining})')
            return redirect('payments:detail', pk=pk)

        # Create allocation
        PaymentAllocation.objects.create(
            payment=payment,
            content_type=ct,
            object_id=doc.pk,
            amount=amount,
        )

        messages.success(request, 'تم تخصيص الدفعة بنجاح')

    return redirect('payments:detail', pk=pk)


@login_required
@posting_permission_required
def payment_deallocate(request, pk, allocation_pk):
    """Remove a payment allocation."""
    payment = get_object_or_404(Payment, pk=pk)
    allocation = get_object_or_404(PaymentAllocation, pk=allocation_pk, payment=payment)

    if request.method == 'POST':
        allocation.delete()
        messages.success(request, 'تم إلغاء التخصيص')

    return redirect('payments:detail', pk=pk)
