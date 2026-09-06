"""
Admin configuration for accounting app.
"""
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import AccountType, Account, Journal, JournalEntry, JournalLine


@admin.register(AccountType)
class AccountTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'normal_balance', 'report_section', 'order')
    ordering = ('order', 'code')


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 2
    fields = ('line_number', 'account', 'description', 'debit', 'credit', 'partner', 'project')


@admin.register(Account)
class AccountAdmin(SimpleHistoryAdmin):
    list_display = ('code', 'name', 'account_type', 'parent', 'is_control', 'is_active')
    list_filter = ('account_type', 'is_control', 'is_active')
    search_fields = ('code', 'name')
    ordering = ('code',)


@admin.register(Journal)
class JournalAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'type', 'is_active', 'next_number')
    list_filter = ('type', 'is_active')
    ordering = ('code',)


@admin.register(JournalEntry)
class JournalEntryAdmin(SimpleHistoryAdmin):
    list_display = ('entry_number', 'journal', 'date', 'is_posted', 'is_reversed', 'posted_by')
    list_filter = ('journal', 'is_posted', 'is_reversed', 'date')
    search_fields = ('entry_number', 'reference', 'memo')
    date_hierarchy = 'date'
    inlines = [JournalLineInline]
    readonly_fields = ('entry_number', 'is_posted', 'posted_at', 'posted_by', 'is_reversed', 'reversed_by')
