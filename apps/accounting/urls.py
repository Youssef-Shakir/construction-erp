"""
URL patterns for accounting app.
"""
from django.urls import path
from . import views

app_name = 'accounting'

urlpatterns = [
    # Chart of Accounts
    path('accounts/', views.account_list, name='accounts'),
    path('accounts/new/', views.account_create, name='account_create'),
    path('accounts/<int:pk>/edit/', views.account_edit, name='account_edit'),

    # Journals
    path('journals/', views.journal_list, name='journals'),
    path('journals/new/', views.journal_create, name='journal_create'),
    path('journals/<int:pk>/edit/', views.journal_edit, name='journal_edit'),

    # Journal Entries
    path('entries/', views.entry_list, name='entries'),
    path('entries/new/', views.entry_create, name='entry_create'),
    path('entries/<int:pk>/', views.entry_detail, name='entry_detail'),
    path('entries/<int:pk>/reverse/', views.entry_reverse, name='entry_reverse'),

    # Ledger & Reports
    path('ledger/', views.ledger, name='ledger'),
    path('trial-balance/', views.trial_balance, name='trial_balance'),
    path('income-statement/', views.income_statement, name='income_statement'),
    path('balance-sheet/', views.balance_sheet, name='balance_sheet'),
    path('receivables/', views.receivables, name='receivables'),
    path('payables/', views.payables, name='payables'),
]
