"""
URL patterns for bills.
"""
from django.urls import path
from . import views

app_name = 'bills'

urlpatterns = [
    path('', views.bill_list, name='list'),
    path('new/', views.bill_create, name='create'),
    path('<int:pk>/', views.bill_detail, name='detail'),
    path('<int:pk>/edit/', views.bill_edit, name='edit'),
    path('<int:pk>/post/', views.bill_post, name='post'),
    path('<int:pk>/cancel/', views.bill_cancel, name='cancel'),
]
