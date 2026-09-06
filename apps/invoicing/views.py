"""
Views for invoicing app (Invoice and Bill).
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator
from django.utils import timezone
from django.http import HttpResponse
from django.template.loader import render_to_string
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType

from apps.accounts.permissions import can_post_document, posting_permission_required
from apps.accounting.posting import PostingError
from apps.core.models import Attachment, CompanySettings
from .models import Invoice, Bill
from .forms import InvoiceForm, BillForm


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


# Invoice views
@login_required
def invoice_list(request):
    """List all invoices."""
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    project_id = request.GET.get('project', '')

    invoices = Invoice.objects.select_related(
        'project', 'customer'
    ).order_by('-date', '-invoice_number')

    if query:
        invoices = invoices.filter(
            Q(invoice_number__icontains=query) |
            Q(customer__name__icontains=query) |
            Q(description__icontains=query)
        )

    if status == 'draft':
        invoices = invoices.filter(status='draft')
    elif status == 'posted':
        invoices = invoices.filter(status='posted')
    elif status == 'cancelled':
        invoices = invoices.filter(status='cancelled')
    elif status == 'overdue':
        invoices = invoices.filter(status='posted', due_date__lt=timezone.now().date())
    elif status == 'unpaid':
        invoices = invoices.filter(status='posted')

    if project_id:
        invoices = invoices.filter(project_id=project_id)

    paginator = Paginator(invoices, 25)
    page = request.GET.get('page', 1)
    invoices = paginator.get_page(page)

    return render(request, 'invoicing/invoice_list.html', {
        'invoices': invoices,
        'page_obj': invoices,
        'query': query,
        'status': status,
        'project_id': project_id,
    })


@login_required
def invoice_create(request):
    """Create a new invoice."""
    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.amount_base = invoice.amount
            invoice.created_by = request.user
            invoice.updated_by = request.user
            invoice.save()

            # Handle file attachments
            _save_attachments(request, Invoice, invoice.pk)

            messages.success(request, f'تم إنشاء الفاتورة {invoice.invoice_number}')
            return redirect('invoicing:detail', pk=invoice.pk)
    else:
        # Default due date: 30 days from today
        form = InvoiceForm(initial={
            'date': timezone.now().date(),
            'due_date': timezone.now().date() + timedelta(days=30),
        })

    return render(request, 'invoicing/invoice_form.html', {
        'form': form,
        'title': 'فاتورة جديدة',
    })


@login_required
def invoice_edit(request, pk):
    """Edit a draft invoice."""
    invoice = get_object_or_404(Invoice, pk=pk)

    if invoice.status != 'draft':
        messages.error(request, 'لا يمكن تعديل فاتورة مرحّلة')
        return redirect('invoicing:detail', pk=pk)

    if request.method == 'POST':
        form = InvoiceForm(request.POST, instance=invoice)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.amount_base = invoice.amount
            invoice.updated_by = request.user
            invoice.save()
            messages.success(request, f'تم تحديث الفاتورة {invoice.invoice_number}')
            return redirect('invoicing:detail', pk=invoice.pk)
    else:
        form = InvoiceForm(instance=invoice)

    return render(request, 'invoicing/invoice_form.html', {
        'form': form,
        'title': f'تعديل الفاتورة: {invoice.invoice_number}',
        'invoice': invoice,
    })


@login_required
def invoice_detail(request, pk):
    """View invoice details."""
    from django.contrib.contenttypes.models import ContentType
    from apps.core.models import Attachment

    invoice = get_object_or_404(
        Invoice.objects.select_related('project', 'customer', 'journal_entry'),
        pk=pk
    )

    # Get attachments
    content_type = ContentType.objects.get_for_model(Invoice)
    attachments = Attachment.objects.filter(
        content_type=content_type,
        object_id=invoice.pk
    ).select_related('uploaded_by')

    # Get history records
    history_records = invoice.history.all()[:50]

    return render(request, 'invoicing/invoice_detail.html', {
        'invoice': invoice,
        'can_post': can_post_document(request.user),
        'content_type_id': content_type.pk,
        'object_id': invoice.pk,
        'attachments': attachments,
        'history_records': history_records,
    })


@login_required
@posting_permission_required
def invoice_post(request, pk):
    """Post a draft invoice."""
    invoice = get_object_or_404(Invoice, pk=pk)

    if request.method == 'POST':
        try:
            invoice.post(user=request.user)
            messages.success(request, f'تم ترحيل الفاتورة {invoice.invoice_number}')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('invoicing:detail', pk=pk)


@login_required
@posting_permission_required
def invoice_cancel(request, pk):
    """Cancel a posted invoice."""
    invoice = get_object_or_404(Invoice, pk=pk)

    if request.method == 'POST':
        try:
            invoice.cancel(user=request.user)
            messages.success(request, f'تم إلغاء الفاتورة {invoice.invoice_number}')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('invoicing:detail', pk=pk)


# Bill views
@login_required
def bill_list(request):
    """List all bills."""
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    project_id = request.GET.get('project', '')

    bills = Bill.objects.select_related(
        'project', 'supplier', 'account'
    ).order_by('-date', '-bill_number')

    if query:
        bills = bills.filter(
            Q(bill_number__icontains=query) |
            Q(supplier__name__icontains=query) |
            Q(vendor_reference__icontains=query)
        )

    if status == 'draft':
        bills = bills.filter(status='draft')
    elif status == 'posted':
        bills = bills.filter(status='posted')
    elif status == 'cancelled':
        bills = bills.filter(status='cancelled')
    elif status == 'overdue':
        bills = bills.filter(status='posted', due_date__lt=timezone.now().date())

    if project_id:
        bills = bills.filter(project_id=project_id)

    paginator = Paginator(bills, 25)
    page = request.GET.get('page', 1)
    bills = paginator.get_page(page)

    return render(request, 'invoicing/bill_list.html', {
        'bills': bills,
        'page_obj': bills,
        'query': query,
        'status': status,
        'project_id': project_id,
    })


@login_required
def bill_create(request):
    """Create a new bill."""
    if request.method == 'POST':
        form = BillForm(request.POST)
        if form.is_valid():
            bill = form.save(commit=False)
            bill.amount_base = bill.amount
            bill.created_by = request.user
            bill.updated_by = request.user
            bill.save()

            # Handle file attachments
            _save_attachments(request, Bill, bill.pk)

            messages.success(request, f'تم إنشاء فاتورة المورد {bill.bill_number}')
            return redirect('bills:detail', pk=bill.pk)
    else:
        form = BillForm(initial={
            'date': timezone.now().date(),
            'due_date': timezone.now().date() + timedelta(days=30),
        })

    return render(request, 'invoicing/bill_form.html', {
        'form': form,
        'title': 'فاتورة مورد جديدة',
    })


@login_required
def bill_edit(request, pk):
    """Edit a draft bill."""
    bill = get_object_or_404(Bill, pk=pk)

    if bill.status != 'draft':
        messages.error(request, 'لا يمكن تعديل فاتورة مرحّلة')
        return redirect('bills:detail', pk=pk)

    if request.method == 'POST':
        form = BillForm(request.POST, instance=bill)
        if form.is_valid():
            bill = form.save(commit=False)
            bill.amount_base = bill.amount
            bill.updated_by = request.user
            bill.save()
            messages.success(request, f'تم تحديث فاتورة المورد {bill.bill_number}')
            return redirect('bills:detail', pk=bill.pk)
    else:
        form = BillForm(instance=bill)

    return render(request, 'invoicing/bill_form.html', {
        'form': form,
        'title': f'تعديل فاتورة المورد: {bill.bill_number}',
        'bill': bill,
    })


@login_required
def bill_detail(request, pk):
    """View bill details."""
    from django.contrib.contenttypes.models import ContentType
    from apps.core.models import Attachment

    bill = get_object_or_404(
        Bill.objects.select_related('project', 'supplier', 'account', 'journal_entry'),
        pk=pk
    )

    # Get attachments
    content_type = ContentType.objects.get_for_model(Bill)
    attachments = Attachment.objects.filter(
        content_type=content_type,
        object_id=bill.pk
    ).select_related('uploaded_by')

    # Get history records
    history_records = bill.history.all()[:50]

    return render(request, 'invoicing/bill_detail.html', {
        'bill': bill,
        'can_post': can_post_document(request.user),
        'content_type_id': content_type.pk,
        'object_id': bill.pk,
        'attachments': attachments,
        'history_records': history_records,
    })


@login_required
@posting_permission_required
def bill_post(request, pk):
    """Post a draft bill."""
    bill = get_object_or_404(Bill, pk=pk)

    if request.method == 'POST':
        try:
            bill.post(user=request.user)
            messages.success(request, f'تم ترحيل فاتورة المورد {bill.bill_number}')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('bills:detail', pk=pk)


@login_required
@posting_permission_required
def bill_cancel(request, pk):
    """Cancel a posted bill."""
    bill = get_object_or_404(Bill, pk=pk)

    if request.method == 'POST':
        try:
            bill.cancel(user=request.user)
            messages.success(request, f'تم إلغاء فاتورة المورد {bill.bill_number}')
        except PostingError as e:
            messages.error(request, str(e))

    return redirect('bills:detail', pk=pk)


@login_required
def invoice_pdf(request, pk):
    """Generate PDF for invoice."""
    invoice = get_object_or_404(
        Invoice.objects.select_related('project', 'customer'),
        pk=pk
    )
    company = CompanySettings.get_settings()

    # Render HTML template
    html_string = render_to_string('invoicing/invoice_pdf.html', {
        'invoice': invoice,
        'company': company,
    })

    # Try to use weasyprint, fallback to HTML
    try:
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration

        font_config = FontConfiguration()
        html = HTML(string=html_string)
        css = CSS(string='''
            @page { size: A4; margin: 1.5cm; }
            body { font-family: Arial, sans-serif; direction: rtl; }
        ''', font_config=font_config)

        pdf = html.write_pdf(stylesheets=[css], font_config=font_config)

        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="invoice_{invoice.invoice_number}.pdf"'
        return response
    except ImportError:
        # Fallback: return printable HTML page
        return render(request, 'invoicing/invoice_pdf.html', {
            'invoice': invoice,
            'company': company,
        })


@login_required
def invoice_print(request, pk):
    """Print view for invoice."""
    invoice = get_object_or_404(
        Invoice.objects.select_related('project', 'customer'),
        pk=pk
    )
    company = CompanySettings.get_settings()

    return render(request, 'invoicing/invoice_print.html', {
        'invoice': invoice,
        'company': company,
    })
