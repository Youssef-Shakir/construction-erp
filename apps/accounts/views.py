"""
Views for accounts app - authentication and user management.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib import messages
from django.db.models import Q

from .models import User
from .forms import LoginForm, UserForm, UserEditForm, PasswordChangeForm
from .permissions import business_manager_required


def login_view(request):
    """User login view."""
    if request.user.is_authenticated:
        return redirect('dashboard:home')

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            user = authenticate(request, username=email, password=password)
            if user is not None:
                if user.is_active:
                    login(request, user)
                    # Only follow ?next= to this site (prevents open redirects).
                    next_url = request.POST.get('next') or request.GET.get('next')
                    if next_url and url_has_allowed_host_and_scheme(
                        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
                    ):
                        return redirect(next_url)
                    return redirect('dashboard:home')
                else:
                    messages.error(request, 'هذا الحساب غير نشط')
            else:
                messages.error(request, 'البريد الإلكتروني أو كلمة المرور غير صحيحة')
    else:
        form = LoginForm()

    return render(request, 'accounts/login.html', {'form': form})


@require_POST
def logout_view(request):
    """User logout view (POST only, so other sites can't log users out)."""
    logout(request)
    messages.success(request, 'تم تسجيل الخروج بنجاح')
    return redirect('accounts:login')


@login_required
@business_manager_required
def user_list(request):
    """List all users."""
    query = request.GET.get('q', '')
    users = User.objects.all()

    if query:
        users = users.filter(
            Q(email__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )

    users = users.prefetch_related('groups').order_by('first_name', 'last_name')

    return render(request, 'accounts/user_list.html', {
        'users': users,
        'query': query,
    })


@login_required
@business_manager_required
def user_create(request):
    """Create a new user."""
    if request.method == 'POST':
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()

            # Assign group/role
            role = form.cleaned_data.get('role')
            if role:
                group, _ = Group.objects.get_or_create(name=role)
                user.groups.add(group)

            messages.success(request, f'تم إنشاء المستخدم {user.get_full_name()} بنجاح')
            return redirect('accounts:users')
    else:
        form = UserForm()

    return render(request, 'accounts/user_form.html', {
        'form': form,
        'title': 'إضافة مستخدم جديد',
    })


@login_required
@business_manager_required
def user_edit(request, pk):
    """Edit an existing user."""
    user = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=user)
        if form.is_valid():
            user = form.save()

            # Update group/role
            role = form.cleaned_data.get('role')
            user.groups.clear()
            if role:
                group, _ = Group.objects.get_or_create(name=role)
                user.groups.add(group)

            messages.success(request, f'تم تحديث المستخدم {user.get_full_name()} بنجاح')
            return redirect('accounts:users')
    else:
        # Get current role
        current_role = None
        for group in user.groups.all():
            if group.name in ['BusinessManager', 'Accountant', 'DataEntry']:
                current_role = group.name
                break
        form = UserEditForm(instance=user, initial={'role': current_role})

    return render(request, 'accounts/user_form.html', {
        'form': form,
        'title': f'تعديل المستخدم: {user.get_full_name()}',
        'user_obj': user,
    })


@login_required
@business_manager_required
def user_toggle_active(request, pk):
    """Toggle user active status."""
    user = get_object_or_404(User, pk=pk)

    if user == request.user:
        messages.error(request, 'لا يمكنك تعطيل حسابك الخاص')
    else:
        user.is_active = not user.is_active
        user.save()
        status = 'تفعيل' if user.is_active else 'تعطيل'
        messages.success(request, f'تم {status} المستخدم {user.get_full_name()}')

    return redirect('accounts:users')


@login_required
@business_manager_required
def user_change_password(request, pk):
    """Change user password (by admin)."""
    user = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        form = PasswordChangeForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data['password'])
            user.save()
            messages.success(request, f'تم تغيير كلمة مرور {user.get_full_name()} بنجاح')
            return redirect('accounts:users')
    else:
        form = PasswordChangeForm()

    return render(request, 'accounts/password_change.html', {
        'form': form,
        'user_obj': user,
    })


@login_required
def profile(request):
    """User profile / change own password."""
    if request.method == 'POST':
        form = PasswordChangeForm(request.POST)
        if form.is_valid():
            request.user.set_password(form.cleaned_data['password'])
            request.user.save()
            messages.success(request, 'تم تغيير كلمة المرور بنجاح. يرجى تسجيل الدخول مرة أخرى.')
            return redirect('accounts:login')
    else:
        form = PasswordChangeForm()

    return render(request, 'accounts/profile.html', {
        'form': form,
    })
