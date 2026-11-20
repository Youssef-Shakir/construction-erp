"""
URL patterns for expenses app.
"""
from django.urls import path
from . import views

app_name = 'expenses'

urlpatterns = [
    # Expenses
    path('', views.expense_list, name='list'),
    path('new/', views.expense_create, name='create'),
    path('<int:pk>/', views.expense_detail, name='detail'),
    path('<int:pk>/edit/', views.expense_edit, name='edit'),
    path('<int:pk>/post/', views.expense_post, name='post'),
    path('<int:pk>/cancel/', views.expense_cancel, name='cancel'),

    # Expense Batches (مستندات مصاريف - فقرات على سلفة)
    path('batches/<int:pk>/', views.batch_detail, name='batch_detail'),
    path('batches/<int:pk>/post/', views.batch_post, name='batch_post'),
    path('batches/<int:pk>/cancel/', views.batch_cancel, name='batch_cancel'),

    # Paper Receipts
    path('receipts/', views.receipt_list, name='receipts'),
    path('receipts/new/', views.receipt_create, name='receipt_create'),
]
