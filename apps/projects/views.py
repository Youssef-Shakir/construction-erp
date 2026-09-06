"""
Views for projects app.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator

from .models import Project
from .forms import ProjectForm


@login_required
def project_list(request):
    """List all projects."""
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')

    projects = Project.objects.select_related('customer').all()

    if query:
        projects = projects.filter(
            Q(code__icontains=query) |
            Q(name__icontains=query) |
            Q(customer__name__icontains=query)
        )

    if status:
        projects = projects.filter(status=status)

    projects = projects.order_by('-created_at')

    # Pagination
    paginator = Paginator(projects, 25)
    page = request.GET.get('page', 1)
    projects = paginator.get_page(page)

    return render(request, 'projects/project_list.html', {
        'projects': projects,
        'page_obj': projects,
        'query': query,
        'status': status,
    })


@login_required
def project_create(request):
    """Create a new project."""
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.created_by = request.user
            project.updated_by = request.user
            project.save()
            messages.success(request, f'تم إنشاء المشروع {project.name} بنجاح')
            return redirect('projects:detail', pk=project.pk)
    else:
        form = ProjectForm()

    return render(request, 'projects/project_form.html', {
        'form': form,
        'title': 'إضافة مشروع جديد',
    })


@login_required
def project_edit(request, pk):
    """Edit an existing project."""
    project = get_object_or_404(Project, pk=pk)

    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            project = form.save(commit=False)
            project.updated_by = request.user
            project.save()
            messages.success(request, f'تم تحديث المشروع {project.name} بنجاح')
            return redirect('projects:detail', pk=project.pk)
    else:
        form = ProjectForm(instance=project)

    return render(request, 'projects/project_form.html', {
        'form': form,
        'title': f'تعديل المشروع: {project.name}',
        'project': project,
    })


@login_required
def project_detail(request, pk):
    """View project details with financial summary."""
    from django.contrib.contenttypes.models import ContentType
    from apps.core.models import Attachment
    from apps.invoicing.models import Invoice, Bill
    from apps.expenses.models import Expense
    from apps.advances.models import CashAdvance

    project = get_object_or_404(Project.objects.select_related('customer'), pk=pk)

    # Get related documents
    invoices = Invoice.objects.filter(project=project).select_related('customer').order_by('-date')
    bills = Bill.objects.filter(project=project).select_related('supplier', 'account').order_by('-date')
    expenses = Expense.objects.filter(project=project).select_related('account', 'advance').order_by('-date')
    advances = CashAdvance.objects.filter(project=project).select_related('recipient').order_by('-date')

    # Get attachments
    content_type = ContentType.objects.get_for_model(Project)
    attachments = Attachment.objects.filter(
        content_type=content_type,
        object_id=project.pk
    ).select_related('uploaded_by')

    # Get history
    history_records = project.history.all()[:50]

    context = {
        'project': project,
        'invoices': invoices,
        'bills': bills,
        'expenses': expenses,
        'advances': advances,
        'content_type_id': content_type.pk,
        'object_id': project.pk,
        'attachments': attachments,
        'history_records': history_records,
    }

    return render(request, 'projects/project_detail.html', context)
