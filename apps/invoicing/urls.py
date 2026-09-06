"""
URL patterns for invoices.
"""
from django.urls import path
from . import views

app_name = 'invoicing'

urlpatterns = [
    path('', views.invoice_list, name='list'),
    path('new/', views.invoice_create, name='create'),
    path('<int:pk>/', views.invoice_detail, name='detail'),
    path('<int:pk>/edit/', views.invoice_edit, name='edit'),
    path('<int:pk>/post/', views.invoice_post, name='post'),
    path('<int:pk>/cancel/', views.invoice_cancel, name='cancel'),
    path('<int:pk>/pdf/', views.invoice_pdf, name='pdf'),
    path('<int:pk>/print/', views.invoice_print, name='print'),
]
