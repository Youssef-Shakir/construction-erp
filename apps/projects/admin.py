"""
Admin configuration for projects app.
"""
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import Project


@admin.register(Project)
class ProjectAdmin(SimpleHistoryAdmin):
    list_display = ('code', 'name', 'customer', 'status', 'start_date', 'budget')
    list_filter = ('status', 'created_at')
    search_fields = ('code', 'name', 'customer__name')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'

    fieldsets = (
        (None, {
            'fields': ('code', 'name', 'customer', 'status')
        }),
        ('التفاصيل', {
            'fields': ('start_date', 'end_date', 'budget', 'description')
        }),
    )
