"""
Admin configuration for advances app.
"""
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import CashAdvance, AdvanceReturn


class AdvanceReturnInline(admin.TabularInline):
    model = AdvanceReturn
    extra = 0
    fields = ('return_number', 'date', 'amount', 'status')
    readonly_fields = ('return_number', 'status')


@admin.register(CashAdvance)
class CashAdvanceAdmin(SimpleHistoryAdmin):
    list_display = ('advance_number', 'project', 'recipient', 'date', 'amount', 'status', 'remaining')
    list_filter = ('status', 'project', 'date')
    search_fields = ('advance_number', 'recipient__name', 'project__name')
    date_hierarchy = 'date'
    inlines = [AdvanceReturnInline]

    fieldsets = (
        (None, {
            'fields': ('advance_number', 'status')
        }),
        ('التفاصيل', {
            'fields': ('project', 'recipient', 'date', 'purpose')
        }),
        ('المبلغ', {
            'fields': ('amount', 'currency', 'amount_base')
        }),
        ('المحاسبة', {
            'fields': ('journal_entry',)
        }),
    )
    readonly_fields = ('advance_number', 'status', 'journal_entry')

    def remaining(self, obj):
        return obj.remaining
    remaining.short_description = 'المتبقي'


@admin.register(AdvanceReturn)
class AdvanceReturnAdmin(SimpleHistoryAdmin):
    list_display = ('return_number', 'advance', 'date', 'amount', 'status')
    list_filter = ('status', 'date')
    search_fields = ('return_number', 'advance__advance_number')
    date_hierarchy = 'date'
