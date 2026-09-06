"""
Admin configuration for invoicing app.
"""
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import Invoice, Bill


@admin.register(Invoice)
class InvoiceAdmin(SimpleHistoryAdmin):
    list_display = ('invoice_number', 'customer', 'project', 'date', 'amount', 'status', 'payment_status')
    list_filter = ('status', 'project', 'date')
    search_fields = ('invoice_number', 'customer__name', 'description')
    date_hierarchy = 'date'
    readonly_fields = ('invoice_number', 'status', 'journal_entry')

    def payment_status(self, obj):
        return obj.payment_status
    payment_status.short_description = 'حالة الدفع'


@admin.register(Bill)
class BillAdmin(SimpleHistoryAdmin):
    list_display = ('bill_number', 'supplier', 'project', 'date', 'amount', 'status', 'payment_status')
    list_filter = ('status', 'project', 'date')
    search_fields = ('bill_number', 'supplier__name', 'vendor_reference')
    date_hierarchy = 'date'
    readonly_fields = ('bill_number', 'status', 'journal_entry')

    def payment_status(self, obj):
        return obj.payment_status
    payment_status.short_description = 'حالة الدفع'
