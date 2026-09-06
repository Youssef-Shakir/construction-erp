"""
Admin configuration for payments app.
"""
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import Payment, PaymentAllocation


class PaymentAllocationInline(admin.TabularInline):
    model = PaymentAllocation
    extra = 0
    readonly_fields = ('content_type', 'object_id', 'amount')


@admin.register(Payment)
class PaymentAdmin(SimpleHistoryAdmin):
    list_display = ('payment_number', 'direction', 'partner', 'date', 'amount', 'status', 'unallocated_amount')
    list_filter = ('direction', 'status', 'date')
    search_fields = ('payment_number', 'partner__name', 'reference')
    date_hierarchy = 'date'
    readonly_fields = ('payment_number', 'status', 'journal_entry')
    inlines = [PaymentAllocationInline]

    def unallocated_amount(self, obj):
        return obj.unallocated_amount
    unallocated_amount.short_description = 'غير مخصص'
