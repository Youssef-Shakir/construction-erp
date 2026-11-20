"""
Dashboard views.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .services import build_dashboard


@login_required
def dashboard(request):
    """Work queue + financial position. Financial figures only for report roles."""
    return render(request, 'dashboard/dashboard.html', build_dashboard(request.user))
