"""
One place that turns an HTML template into a PDF (WeasyPrint).

Every printable document (invoice, payment voucher, statements, project
report) extends templates/pdf/base.html, which takes the company header,
logo, colour, footer and signature boxes from CompanySettings - so the
owner edits the look of all PDFs from the company settings page.
"""
import base64
import logging

from django.http import HttpResponse
from django.template.loader import render_to_string

from .models import CompanySettings

logger = logging.getLogger(__name__)


def logo_data_uri(company):
    """The company logo inlined as a data: URI (works with a private S3 bucket)."""
    if not company.logo:
        return ''
    try:
        with company.logo.open('rb') as fh:
            data = fh.read()
    except Exception:  # missing file must not break printing
        logger.warning('Company logo could not be read', exc_info=True)
        return ''
    ext = company.logo.name.rsplit('.', 1)[-1].lower()
    mime = {'jpg': 'jpeg', 'svg': 'svg+xml'}.get(ext, ext)
    return f'data:image/{mime};base64,{base64.b64encode(data).decode()}'


def pdf_context(extra):
    company = CompanySettings.get_settings()
    return {'company': company, 'logo_src': logo_data_uri(company), **extra}


def render_pdf(request, template_name, context, filename, *, download=False):
    """Render `template_name` to a PDF response (HTML fallback if WeasyPrint is missing)."""
    html = render_to_string(template_name, pdf_context(context), request=request)
    try:
        from weasyprint import HTML
    except ImportError:  # pragma: no cover - dev machines without Pango
        return HttpResponse(html)
    pdf = HTML(string=html).write_pdf()   # no base_url: nothing is fetched over the network
    response = HttpResponse(pdf, content_type='application/pdf')
    disposition = 'attachment' if download else 'inline'
    response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
    return response
