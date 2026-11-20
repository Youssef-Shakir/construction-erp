"""
Views for core app - company settings, partners, documents/attachments.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from urllib.parse import quote

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.contrib.contenttypes.models import ContentType

from apps.accounts.permissions import (
    business_manager_required, can_delete_attachment, can_manage_scan_inbox,
    can_upload_attachments, can_view_attachment,
)
from .attachments import (
    ACCEPT_ATTR, AttachmentError, assign_to_document, attachable_content_type_ids,
    attachments_for, describe_document, find_document_by_number, inbox_items,
    prepare_files, store_attachments,
)
from .models import CompanySettings, Partner, Attachment
from .forms import CompanySettingsForm, PartnerForm, AttachmentForm


@login_required
@business_manager_required
def company_settings(request):
    """Company settings view."""
    settings_obj = CompanySettings.get_settings()

    if request.method == 'POST':
        form = CompanySettingsForm(request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم حفظ إعدادات الشركة بنجاح')
            return redirect('core:company_settings')
    else:
        form = CompanySettingsForm(instance=settings_obj)

    return render(request, 'core/company_settings.html', {
        'form': form,
        'settings': settings_obj,
    })


@login_required
def company_logo(request):
    """Serve the company logo from any storage backend (private bucket safe)."""
    logo = CompanySettings.get_settings().logo
    if not logo:
        raise Http404
    try:
        fh = logo.open('rb')
    except Exception:
        raise Http404
    response = FileResponse(fh, content_type='image/' + (logo.name.rsplit('.', 1)[-1].lower().replace('jpg', 'jpeg')))
    response['Cache-Control'] = 'private, max-age=3600'
    return response


# Partner views
@login_required
def partner_list(request):
    """List all partners."""
    query = request.GET.get('q', '')
    partner_type = request.GET.get('type', '')

    partners = Partner.objects.all()

    if query:
        partners = partners.filter(
            Q(code__icontains=query) |
            Q(name__icontains=query) |
            Q(email__icontains=query) |
            Q(phone__icontains=query)
        )

    if partner_type:
        partners = partners.filter(type=partner_type)

    partners = partners.order_by('name')

    return render(request, 'core/partner_list.html', {
        'partners': partners,
        'query': query,
        'partner_type': partner_type,
    })


@login_required
def partner_create(request):
    """Create a new partner."""
    if request.method == 'POST':
        form = PartnerForm(request.POST)
        if form.is_valid():
            partner = form.save(commit=False)
            partner.created_by = request.user
            partner.updated_by = request.user
            partner.save()
            messages.success(request, f'تم إنشاء الشريك {partner.name} بنجاح')
            return redirect('core:partners')
    else:
        # Pre-fill type from URL parameter
        initial = {}
        if request.GET.get('type'):
            initial['type'] = request.GET.get('type')
        form = PartnerForm(initial=initial)

    return render(request, 'core/partner_form.html', {
        'form': form,
        'title': 'إضافة شريك جديد',
    })


@login_required
def partner_edit(request, pk):
    """Edit an existing partner."""
    partner = get_object_or_404(Partner, pk=pk)

    if request.method == 'POST':
        form = PartnerForm(request.POST, instance=partner)
        if form.is_valid():
            partner = form.save(commit=False)
            partner.updated_by = request.user
            partner.save()
            messages.success(request, f'تم تحديث الشريك {partner.name} بنجاح')
            return redirect('core:partners')
    else:
        form = PartnerForm(instance=partner)

    return render(request, 'core/partner_form.html', {
        'form': form,
        'title': f'تعديل الشريك: {partner.name}',
        'partner': partner,
    })


@login_required
def partner_detail(request, pk):
    """View partner details."""
    partner = get_object_or_404(Partner, pk=pk)
    return render(request, 'core/partner_detail.html', {
        'partner': partner,
    })


# Documents/Attachments views
@login_required
def documents(request):
    """List all attachments/documents."""
    from django.core.paginator import Paginator

    query = request.GET.get('q', '')

    attachments = Attachment.objects.filter(content_type__isnull=False).select_related(
        'content_type', 'uploaded_by'
    ).prefetch_related('content_object').order_by('-uploaded_at')

    if query:
        attachments = attachments.filter(
            Q(original_filename__icontains=query) |
            Q(description__icontains=query)
        )

    paginator = Paginator(attachments, 50)
    page = request.GET.get('page', 1)
    attachments = paginator.get_page(page)
    for att in attachments:
        doc = att.content_object
        att.doc_label, att.doc_number, att.doc_url = describe_document(doc) if doc else ('', '-', None)

    return render(request, 'core/documents.html', {
        'attachments': attachments,
        'query': query,
        'inbox_count': inbox_items().count(),
    })


def _document_from_post(request):
    """Resolve (content_type, object) from POSTed ids, only for attachable documents."""
    ct_id = request.POST.get('content_type_id', '')
    obj_id = request.POST.get('object_id', '')
    if not (ct_id.isdigit() and obj_id.isdigit()):
        raise Http404
    if int(ct_id) not in attachable_content_type_ids():
        raise Http404
    content_type = get_object_or_404(ContentType, pk=ct_id)
    obj = get_object_or_404(content_type.model_class(), pk=obj_id)
    return content_type, obj


def _render_attachment_list(request, content_type, obj, notices=None):
    return render(request, 'partials/attachment_list.html', {
        'attachments': attachments_for(obj),
        'content_type_id': content_type.pk,
        'object_id': obj.pk,
        'notices': notices or [],
    })


@login_required
@require_POST
def attachment_upload(request):
    """
    HTMX endpoint: upload one or more files (file picker, drag & drop,
    phone camera, or scanner output) to a document.
    """
    if not can_upload_attachments(request.user):
        return HttpResponseForbidden()
    content_type, obj = _document_from_post(request)

    files = request.FILES.getlist('file')
    notices = []
    if not files:
        notices.append(('error', 'لم يتم اختيار أي ملف'))
    else:
        source = request.POST.get('upload_source', 'upload')
        if source not in ('upload', 'camera', 'scanner'):
            source = 'upload'
        prepared, errors = prepare_files(
            files,
            combine_images=bool(request.POST.get('combine_images')),
            combined_name=request.POST.get('combined_name', '').strip() or None,
        )
        created, skipped = store_attachments(
            prepared, target=obj, user=request.user, source=source,
            description=request.POST.get('description', ''),
        )
        notices += [('error', e) for e in errors]
        if skipped:
            notices.append(('warning', 'ملفات مكررة لم تُرفع: ' + '، '.join(skipped)))
        if created:
            notices.append(('success', f'تم رفع {len(created)} ملف'))

    return _render_attachment_list(request, content_type, obj, notices)


@login_required
@require_POST
def attachment_attach_from_inbox(request):
    """HTMX endpoint: link a scan-inbox item to the current document."""
    if not can_manage_scan_inbox(request.user):
        return HttpResponseForbidden()
    content_type, obj = _document_from_post(request)
    notices = []
    item_id = request.POST.get('attachment_id', '')
    item = Attachment.objects.filter(pk=item_id, content_type__isnull=True).first() if item_id.isdigit() else None
    if item is None:
        notices.append(('error', 'اختر ملفاً من صندوق المسح'))
    else:
        try:
            assign_to_document(item, obj, user=request.user)
            notices.append(('success', f'تم ربط "{item.original_filename}" بالمستند'))
        except AttachmentError as e:
            notices.append(('error', str(e)))
    return _render_attachment_list(request, content_type, obj, notices)


@login_required
@require_POST
def attachment_delete(request, pk):
    """Delete an attachment (document tab or scan inbox)."""
    attachment = get_object_or_404(Attachment, pk=pk)
    if not can_delete_attachment(request.user, attachment):
        if request.headers.get('HX-Request'):
            return HttpResponseForbidden('لا تملك صلاحية حذف هذا المرفق')
        messages.error(request, 'لا تملك صلاحية حذف هذا المرفق')
        return redirect('core:scan_inbox')

    obj = attachment.content_object
    content_type = attachment.content_type
    storage, name = attachment.file.storage, attachment.file.name
    attachment.delete()
    transaction.on_commit(lambda: storage.delete(name))

    if obj is None:
        messages.success(request, 'تم حذف الملف')
        return redirect('core:scan_inbox')
    return _render_attachment_list(request, content_type, obj, [('success', 'تم حذف المرفق')])


@login_required
def attachment_download(request, pk):
    """
    Serve an attachment after a permission check. Media files are never
    served publicly; in production set ATTACHMENT_X_ACCEL_PREFIX so nginx
    streams the file (X-Accel-Redirect) instead of Django.
    """
    attachment = get_object_or_404(Attachment, pk=pk)
    if not can_view_attachment(request.user, attachment):
        return HttpResponseForbidden()

    inline = attachment.can_display_inline and request.GET.get('download') != '1'
    mime = attachment.mime_type or 'application/octet-stream'
    prefix = getattr(settings, 'ATTACHMENT_X_ACCEL_PREFIX', '')

    if prefix:
        response = HttpResponse(content_type=mime)
        response['X-Accel-Redirect'] = prefix.rstrip('/') + '/' + attachment.file.name
    else:
        try:
            fh = attachment.file.open('rb')
        except Exception:  # FileNotFoundError locally, ClientError on S3/MinIO
            raise Http404('الملف غير موجود على الخادم')
        response = FileResponse(fh, content_type=mime)

    disposition = 'inline' if inline else 'attachment'
    response['Content-Disposition'] = f"{disposition}; filename*=UTF-8''{quote(attachment.original_filename)}"
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=3600'
    return response


# --------------------------------------------------------------------------
# Scan inbox: files from scanners / phones not yet linked to a document
# --------------------------------------------------------------------------
@login_required
def scan_inbox(request):
    """
    Scan inbox page. Office scanners drop PDFs into SCAN_INBOX_DIR (imported
    by `manage.py import_scans`), users can also upload / photograph pages
    here; accountants then link each file to its document by number.
    """
    if request.method == 'POST':
        if not can_upload_attachments(request.user):
            return HttpResponseForbidden()
        files = request.FILES.getlist('file')
        if not files:
            messages.error(request, 'لم يتم اختيار أي ملف')
        else:
            source = request.POST.get('upload_source', 'upload')
            if source not in ('upload', 'camera', 'scanner'):
                source = 'upload'
            prepared, errors = prepare_files(
                files,
                combine_images=bool(request.POST.get('combine_images')),
                combined_name=request.POST.get('combined_name', '').strip() or None,
            )
            created, skipped = store_attachments(
                prepared, target=None, user=request.user, source=source,
                description=request.POST.get('description', ''),
            )
            for e in errors:
                messages.error(request, e)
            if skipped:
                messages.warning(request, 'ملفات موجودة مسبقاً في الصندوق: ' + '، '.join(skipped))
            if created:
                messages.success(request, f'تمت إضافة {len(created)} ملف إلى صندوق المسح')
        return redirect('core:scan_inbox')

    return render(request, 'core/scan_inbox.html', {
        'items': inbox_items(),
        'can_manage': can_manage_scan_inbox(request.user),
        'accept': ACCEPT_ATTR,
        'max_mb': getattr(settings, 'ATTACHMENT_MAX_UPLOAD_MB', 25),
    })


@login_required
@require_POST
def scan_inbox_assign(request, pk):
    """Link an inbox item to a document identified by its number (e.g. BILL-000012)."""
    if not can_manage_scan_inbox(request.user):
        messages.error(request, 'ليس لديك صلاحية ربط المستندات')
        return redirect('core:scan_inbox')

    item = get_object_or_404(Attachment, pk=pk, content_type__isnull=True)
    number = request.POST.get('document_number', '')
    target = find_document_by_number(number)
    if target is None:
        messages.error(request, f'لا يوجد مستند بالرقم "{number}"')
        return redirect('core:scan_inbox')

    description = request.POST.get('description', '').strip()
    if description:
        item.description = description[:255]
    try:
        assign_to_document(item, target, user=request.user)
    except AttachmentError as e:
        messages.error(request, str(e))
        return redirect('core:scan_inbox')

    label, doc_number, url = describe_document(target)
    messages.success(request, f'تم ربط "{item.original_filename}" بـ {label} {doc_number}')
    if request.POST.get('next') == 'document' and url:
        return redirect(url)
    return redirect('core:scan_inbox')
