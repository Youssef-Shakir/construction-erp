"""
Progressive Web App endpoints: manifest, service worker, offline page and
the Web Share Target that lets a phone "share" photos/PDFs (from the
gallery or any scanner app) straight into the Scan inbox.

Caching policy (deliberate for an accounting system): only static assets
and the offline page are cached. HTML pages and attachments are never
stored on the device - shared/lost phones must not leak financial data.
"""
import hashlib
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.permissions import can_upload_attachments
from .attachments import ALLOWED_EXTENSIONS, prepare_files, store_attachments

APP_NAME = 'نظام المحاسبة - المقاولات'
SHORT_NAME = 'المحاسبة'
THEME_COLOR = '#2563eb'

PRECACHE_STATIC = [
    'css/output.css',
    'js/htmx.min.js',
    'js/uploads.js',
    'js/pwa.js',
    'pwa/icon-192.png',
    'pwa/icon-512.png',
    'pwa/favicon-32.png',
]


def _assets_version():
    """Changes whenever a precached file changes, so the SW refreshes its cache."""
    digest = hashlib.sha256()
    for path in PRECACHE_STATIC:
        found = finders.find(path)
        if found:
            with open(found, 'rb') as fh:
                digest.update(fh.read())
        digest.update(static(path).encode())
    return digest.hexdigest()[:12]


@require_GET
@cache_control(max_age=3600)
def manifest(request):
    data = {
        'id': '/',
        'name': APP_NAME,
        'short_name': SHORT_NAME,
        'description': 'محاسبة ومتابعة مشاريع المقاولات',
        'lang': 'ar',
        'dir': 'rtl',
        'start_url': reverse('dashboard:home') + '?source=pwa',
        'scope': '/',
        'display': 'standalone',
        'background_color': '#f9fafb',
        'theme_color': THEME_COLOR,
        'icons': [
            {'src': static('pwa/icon-192.png'), 'sizes': '192x192', 'type': 'image/png'},
            {'src': static('pwa/icon-512.png'), 'sizes': '512x512', 'type': 'image/png'},
            {'src': static('pwa/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
        'shortcuts': [
            {'name': 'مسح مستند', 'url': reverse('core:scan_inbox'),
             'icons': [{'src': static('pwa/icon-192.png'), 'sizes': '192x192'}]},
            {'name': 'مصروف جديد', 'url': reverse('expenses:create'),
             'icons': [{'src': static('pwa/icon-192.png'), 'sizes': '192x192'}]},
            {'name': 'فاتورة جديدة', 'url': reverse('invoicing:create'),
             'icons': [{'src': static('pwa/icon-192.png'), 'sizes': '192x192'}]},
        ],
        # Android: "Share" a photo/PDF from any app -> Scan inbox
        'share_target': {
            'action': reverse('pwa_share'),
            'method': 'POST',
            'enctype': 'multipart/form-data',
            'params': {
                'title': 'title',
                'text': 'text',
                'files': [{
                    'name': 'file',
                    'accept': ['image/*', 'application/pdf', *ALLOWED_EXTENSIONS],
                }],
            },
        },
    }
    return HttpResponse(json.dumps(data, ensure_ascii=False), content_type='application/manifest+json')


@require_GET
def service_worker(request):
    response = render(request, 'pwa/sw.js', {
        'version': _assets_version(),
        'precache_json': json.dumps([static(p) for p in PRECACHE_STATIC] + [reverse('pwa_offline')]),
        'offline_url': reverse('pwa_offline'),
        'static_prefix': settings.STATIC_URL if settings.STATIC_URL.startswith('/') else '/' + settings.STATIC_URL,
    }, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    response['Cache-Control'] = 'no-cache'
    return response


@require_GET
def offline(request):
    return render(request, 'pwa/offline.html')


@csrf_exempt  # The OS share sheet can't send a CSRF token. Session cookie is SameSite=Lax,
@require_POST  # so cross-site forged POSTs arrive unauthenticated; worst case is a file
@login_required  # in the inbox, which an accountant must still review and link.
def share_target(request):
    if not can_upload_attachments(request.user):
        return HttpResponseForbidden()
    files = request.FILES.getlist('file')
    if not files:
        messages.error(request, 'لم يصل أي ملف من المشاركة')
        return redirect('core:scan_inbox')

    title = (request.POST.get('title') or request.POST.get('text') or '').strip()
    prepared, errors = prepare_files(files, combine_images=len(files) > 1,
                                     combined_name=title[:100] or None)
    created, skipped = store_attachments(prepared, target=None, user=request.user,
                                         source='camera', description=title[:255])
    for err in errors:
        messages.error(request, err)
    if skipped:
        messages.warning(request, 'ملفات موجودة مسبقاً في الصندوق: ' + '، '.join(skipped))
    if created:
        messages.success(request, f'تمت إضافة {len(created)} ملف إلى صندوق المسح - اربطه بمستنده')
    return redirect('core:scan_inbox')
