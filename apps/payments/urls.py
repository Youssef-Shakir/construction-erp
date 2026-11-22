"""
URL patterns for payments app.
"""
from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('', views.payment_list, name='list'),
    path('receive/', views.payment_create, {'direction': 'inbound'}, name='receive'),
    path('pay/', views.payment_create, {'direction': 'outbound'}, name='pay'),
    path('<int:pk>/pdf/', views.payment_pdf, name='pdf'),
    path('<int:pk>/', views.payment_detail, name='detail'),
    path('<int:pk>/edit/', views.payment_edit, name='edit'),
    path('<int:pk>/post/', views.payment_post, name='post'),
    path('<int:pk>/cancel/', views.payment_cancel, name='cancel'),
    path('<int:pk>/allocate/', views.payment_allocate, name='allocate'),
    path('<int:pk>/deallocate/<int:allocation_pk>/', views.payment_deallocate, name='deallocate'),
]
