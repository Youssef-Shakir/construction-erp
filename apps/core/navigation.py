"""
Helpers for forms opened from another page (e.g. "add expense" on a project):
prefill from the query string and go back where the user came from.
"""
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def safe_next(request):
    """The ?next= URL if it points to this site, else None (no open redirects)."""
    url = request.GET.get('next') or request.POST.get('next')
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return None


def redirect_next(request, *default_args, **default_kwargs):
    """Redirect to ?next= when safe, otherwise to the default view."""
    url = safe_next(request)
    if url:
        return redirect(url)
    return redirect(*default_args, **default_kwargs)


def project_from_query(request):
    """The Project given as ?project=<pk>, or None."""
    from apps.projects.models import Project

    pk = request.GET.get('project', '')
    if not pk.isdigit():
        return None
    return Project.objects.select_related('customer').filter(pk=pk).first()
