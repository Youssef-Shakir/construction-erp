"""
Admin configuration for core app.
"""
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import CompanySettings, Partner, Attachment


@admin.register(CompanySettings)
class CompanySettingsAdmin(admin.ModelAdmin):
    list_display = ('name', 'currency', 'phone', 'email')

    def has_add_permission(self, request):
        # Only allow one instance
        return not CompanySettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Partner)
class PartnerAdmin(SimpleHistoryAdmin):
    list_display = ('code', 'name', 'type', 'phone', 'is_active')
    list_filter = ('type', 'is_active')
    search_fields = ('code', 'name', 'email', 'phone')
    ordering = ('name',)


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ('original_filename', 'content_type', 'object_id', 'uploaded_by', 'uploaded_at')
    list_filter = ('content_type', 'uploaded_at')
    search_fields = ('original_filename', 'description')
    date_hierarchy = 'uploaded_at'
