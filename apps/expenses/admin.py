"""
Admin configuration for expenses app.
"""
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import Expense, PaperReceipt


@admin.register(Expense)
class ExpenseAdmin(SimpleHistoryAdmin):
    list_display = ('expense_number', 'date', 'project', 'account', 'amount', 'status', 'expense_type')
    list_filter = ('status', 'account', 'project', 'date')
    search_fields = ('expense_number', 'description')
    date_hierarchy = 'date'
    readonly_fields = ('expense_number', 'status', 'journal_entry')

    def expense_type(self, obj):
        return obj.expense_type
    expense_type.short_description = 'النوع'


@admin.register(PaperReceipt)
class PaperReceiptAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'vendor_name', 'date', 'amount', 'matched', 'received_from')
    list_filter = ('matched', 'date')
    search_fields = ('receipt_number', 'vendor_name')
    date_hierarchy = 'date'
