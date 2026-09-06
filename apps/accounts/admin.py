"""
Admin configuration for accounts app.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from simple_history.admin import SimpleHistoryAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin, SimpleHistoryAdmin):
    list_display = ('email', 'first_name', 'last_name', 'is_active', 'date_joined')
    list_filter = ('is_active', 'is_staff', 'groups', 'date_joined')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('first_name', 'last_name')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('المعلومات الشخصية', {'fields': ('first_name', 'last_name')}),
        ('الصلاحيات', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('التواريخ', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'password1', 'password2', 'groups'),
        }),
    )
