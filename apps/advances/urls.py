"""
URL patterns for advances app.
"""
from django.urls import path
from . import views

app_name = 'advances'

urlpatterns = [
    # Cash Advances
    path('', views.advance_list, name='list'),
    path('new/', views.advance_create, name='create'),
    path('<int:pk>/', views.advance_detail, name='detail'),
    path('<int:pk>/edit/', views.advance_edit, name='edit'),
    path('<int:pk>/expenses/add/', views.advance_expense_lines, name='expense_lines'),
    path('<int:pk>/post/', views.advance_post, name='post'),
    path('<int:pk>/cancel/', views.advance_cancel, name='cancel'),
    path('<int:pk>/close/', views.advance_close, name='close'),

    # Advance Returns
    path('returns/new/', views.return_create, name='return_create'),
    path('<int:advance_pk>/returns/new/', views.return_create, name='return_create_for'),
    path('returns/<int:pk>/post/', views.return_post, name='return_post'),
    path('returns/<int:pk>/cancel/', views.return_cancel, name='return_cancel'),
]
