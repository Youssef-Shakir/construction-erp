"""
Liveness/readiness endpoint for Docker / load balancers.

Placed FIRST in MIDDLEWARE so it answers before ALLOWED_HOSTS validation and
the HTTPS redirect (container healthchecks call http://localhost:8000).
Exposes nothing but "ok" / "db error".
"""
from django.db import connection
from django.http import HttpResponse


class HealthCheckMiddleware:
    PATH = '/healthz/'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != self.PATH:
            return self.get_response(request)
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except Exception:
            return HttpResponse('db error', status=503, content_type='text/plain')
        return HttpResponse('ok', content_type='text/plain')
