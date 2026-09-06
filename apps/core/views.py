"""
Views for core app - company settings, partners, documents/attachments.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.contenttypes.models import ContentType

from apps.accounts.permissions import business_manager_required
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

    attachments = Attachment.objects.select_related(
        'content_type', 'uploaded_by'
    ).order_by('-uploaded_at')

    if query:
        attachments = attachments.filter(
            Q(original_filename__icontains=query) |
            Q(description__icontains=query)
        )

    paginator = Paginator(attachments, 50)
    page = request.GET.get('page', 1)
    attachments = paginator.get_page(page)

    return render(request, 'core/documents.html', {
        'attachments': attachments,
        'query': query,
    })


@login_required
@require_POST
def attachment_upload(request):
    """HTMX endpoint to upload attachment to a document."""
    content_type_id = request.POST.get('content_type_id')
    object_id = request.POST.get('object_id')

    if not content_type_id or not object_id:
        return JsonResponse({'error': 'Missing parameters'}, status=400)

    content_type = get_object_or_404(ContentType, pk=content_type_id)

    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        attachment = form.save(commit=False)
        attachment.content_type = content_type
        attachment.object_id = object_id
        attachment.uploaded_by = request.user
        attachment.save()

        # Return updated attachment list (HTMX partial)
        attachments = Attachment.objects.filter(
            content_type=content_type,
            object_id=object_id
        ).order_by('-uploaded_at')

        return render(request, 'partials/attachment_list.html', {
            'attachments': attachments,
            'content_type_id': content_type_id,
            'object_id': object_id,
        })

    return JsonResponse({'error': 'Invalid form'}, status=400)


@login_required
@require_POST
def attachment_delete(request, pk):
    """Delete an attachment."""
    attachment = get_object_or_404(Attachment, pk=pk)
    content_type = attachment.content_type
    object_id = attachment.object_id

    attachment.file.delete()  # Delete the file
    attachment.delete()

    # Return updated attachment list (HTMX partial)
    attachments = Attachment.objects.filter(
        content_type=content_type,
        object_id=object_id
    ).order_by('-uploaded_at')

    return render(request, 'partials/attachment_list.html', {
        'attachments': attachments,
        'content_type_id': content_type.pk,
        'object_id': object_id,
    })
