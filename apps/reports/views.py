"""
Statements (كشوف الحساب): customer, supplier and employee-advance statements,
on screen and as PDF, plus a one-page statement for a single cash advance.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts.permissions import accountant_required
from apps.advances.models import CashAdvance
from apps.core.models import Partner
from apps.core.pdf import render_pdf
from apps.projects.models import Project

from .statements import (
    CONTROL_ACCOUNT, advance_statement, employee_advances_summary, partner_statement,
)


def _filters(request):
    """Dates and optional project from the query string (default: this year)."""
    today = timezone.now().date()
    date_from = parse_date(request.GET.get('from', '') or '')
    date_to = parse_date(request.GET.get('to', '') or '')
    if 'from' not in request.GET:
        date_from = today.replace(month=1, day=1)
    if 'to' not in request.GET:
        date_to = today
    project = None
    if (request.GET.get('project') or '').isdigit():
        project = Project.objects.filter(pk=request.GET['project']).first()
    return date_from, date_to, project


def _statement_context(request, partner):
    date_from, date_to, project = _filters(request)
    context = {
        'partner': partner,
        'statement': partner_statement(partner, date_from, date_to, project),
        'project': project,
        'date_from': date_from,
        'date_to': date_to,
    }
    if partner.type == 'employee':
        context['advance_rows'], context['advance_totals'] = employee_advances_summary(partner)
    return context


@login_required
@accountant_required
def statement_index(request):
    """Pick a customer, supplier or employee to print a statement for."""
    partner_type = request.GET.get('type', 'customer')
    if partner_type not in CONTROL_ACCOUNT:
        partner_type = 'customer'
    partners = Partner.objects.filter(type=partner_type, is_active=True).order_by('name')
    return render(request, 'reports/statement_index.html', {
        'partners': partners,
        'partner_type': partner_type,
        'today': timezone.now().date(),
    })


@login_required
@accountant_required
def partner_statement_view(request, pk):
    partner = get_object_or_404(Partner, pk=pk)
    context = _statement_context(request, partner)
    context['projects'] = Project.objects.order_by('code')
    context['query'] = request.GET.urlencode()
    return render(request, 'reports/partner_statement.html', context)


@login_required
@accountant_required
def partner_statement_pdf(request, pk):
    partner = get_object_or_404(Partner, pk=pk)
    return render_pdf(request, 'reports/partner_statement_pdf.html',
                      _statement_context(request, partner),
                      f'statement_{partner.code}.pdf')


@login_required
@accountant_required
def advance_statement_pdf(request, pk):
    advance = get_object_or_404(CashAdvance.objects.select_related('project', 'recipient'), pk=pk)
    return render_pdf(request, 'reports/advance_statement_pdf.html',
                      advance_statement(advance),
                      f'advance_{advance.advance_number}.pdf')
