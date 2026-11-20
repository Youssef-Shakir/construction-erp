"""
Permission helper functions for Construction ERP.

Three roles:
- BusinessManager: Full access to everything (owner)
- Accountant: Full document access, manual journal entries, reports, no user management
- DataEntry: Create/edit drafts only, no posting, no reports, no settings
"""
from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.contrib import messages


def is_business_manager(user):
    """Check if user is a business manager (owner)."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name='BusinessManager').exists()


def is_accountant(user):
    """Check if user is an accountant."""
    if not user.is_authenticated:
        return False
    return user.groups.filter(name='Accountant').exists()


def is_data_entry(user):
    """Check if user is a data entry clerk."""
    if not user.is_authenticated:
        return False
    return user.groups.filter(name='DataEntry').exists()


def can_post_document(user):
    """Check if user can post documents (create journal entries)."""
    return is_business_manager(user) or is_accountant(user)


def can_create_reversal(user):
    """Check if user can create reversal entries."""
    return is_business_manager(user)


def can_create_manual_entry(user):
    """Check if user can create manual journal entries."""
    return is_business_manager(user) or is_accountant(user)


def can_manage_accounts(user):
    """Check if user can manage chart of accounts."""
    return is_business_manager(user)


def can_manage_journals(user):
    """Check if user can manage journals configuration."""
    return is_business_manager(user)


def can_manage_users(user):
    """Check if user can manage users."""
    return is_business_manager(user)


def can_view_reports(user):
    """Check if user can view financial reports."""
    return is_business_manager(user) or is_accountant(user)


def can_view_ledger(user):
    """Check if user can view ledger and accounting entries."""
    return is_business_manager(user) or is_accountant(user)


def can_edit_draft(user):
    """Check if user can edit draft documents."""
    return user.is_authenticated


def can_upload_attachments(user):
    """Check if user can upload attachments."""
    return user.is_authenticated


def can_view_attachment(user, attachment):
    """
    Any active staff role may view document attachments (all roles can open
    the documents themselves). Unauthenticated users never can.
    """
    return user.is_authenticated and user.is_active


def can_delete_attachment(user, attachment):
    """
    - Business manager: always.
    - Attachments of posted/cancelled documents are evidence: manager only.
    - Otherwise the uploader, or anyone who can post documents.
    """
    if not user.is_authenticated:
        return False
    if is_business_manager(user):
        return True
    from apps.core.attachments import document_is_locked
    doc = attachment.content_object
    if doc is not None and document_is_locked(doc):
        return False
    return attachment.uploaded_by_id == user.pk or can_post_document(user)


def can_manage_scan_inbox(user):
    """Assign/delete scan-inbox items: accountants and managers."""
    return can_post_document(user)


# Decorators for views

def business_manager_required(view_func):
    """Decorator requiring business manager role."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_business_manager(request.user):
            messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
            return redirect('dashboard:home')
        return view_func(request, *args, **kwargs)
    return wrapper


def accountant_required(view_func):
    """Decorator requiring accountant or business manager role."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not (is_business_manager(request.user) or is_accountant(request.user)):
            messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
            return redirect('dashboard:home')
        return view_func(request, *args, **kwargs)
    return wrapper


def posting_permission_required(view_func):
    """Decorator requiring posting permission."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not can_post_document(request.user):
            messages.error(request, 'ليس لديك صلاحية لترحيل المستندات')
            return redirect('dashboard:home')
        return view_func(request, *args, **kwargs)
    return wrapper
