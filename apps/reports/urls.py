from django.urls import path

from . import views

app_name = 'reports'

urlpatterns = [
    path('statements/', views.statement_index, name='statements'),
    path('statements/partner/<int:pk>/', views.partner_statement_view, name='partner_statement'),
    path('statements/partner/<int:pk>/pdf/', views.partner_statement_pdf, name='partner_statement_pdf'),
    path('statements/advance/<int:pk>/pdf/', views.advance_statement_pdf, name='advance_statement_pdf'),
]
