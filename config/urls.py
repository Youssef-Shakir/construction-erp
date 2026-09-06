"""
URL configuration for Construction ERP project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # App URLs
    path('', include('apps.dashboard.urls', namespace='dashboard')),
    path('accounts/', include('apps.accounts.urls', namespace='accounts')),
    path('projects/', include('apps.projects.urls', namespace='projects')),
    path('advances/', include('apps.advances.urls', namespace='advances')),
    path('expenses/', include('apps.expenses.urls', namespace='expenses')),
    path('invoices/', include('apps.invoicing.urls', namespace='invoicing')),
    path('bills/', include('apps.invoicing.bill_urls', namespace='bills')),
    path('payments/', include('apps.payments.urls', namespace='payments')),
    path('accounting/', include('apps.accounting.urls', namespace='accounting')),
    path('documents/', include('apps.core.urls', namespace='core')),
]

# Debug toolbar
if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [
        path('__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns

    # Serve media files in development
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
