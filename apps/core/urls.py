"""
URL patterns for core app.
"""
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    # Company settings
    path('settings/company/', views.company_settings, name='company_settings'),

    # Partners
    path('partners/', views.partner_list, name='partners'),
    path('partners/new/', views.partner_create, name='partner_create'),
    path('partners/<int:pk>/', views.partner_detail, name='partner_detail'),
    path('partners/<int:pk>/edit/', views.partner_edit, name='partner_edit'),

    # Documents/Attachments
    path('', views.documents, name='documents'),
    path('attachments/upload/', views.attachment_upload, name='attachment_upload'),
    path('attachments/<int:pk>/delete/', views.attachment_delete, name='attachment_delete'),
    path('attachments/<int:pk>/file/', views.attachment_download, name='attachment_download'),
    path('attachments/from-inbox/', views.attachment_attach_from_inbox, name='attachment_from_inbox'),

    # Scan inbox (scanner / phone camera intake)
    path('inbox/', views.scan_inbox, name='scan_inbox'),
    path('inbox/<int:pk>/assign/', views.scan_inbox_assign, name='scan_inbox_assign'),
]
