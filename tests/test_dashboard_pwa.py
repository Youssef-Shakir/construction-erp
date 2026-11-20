"""Dashboard figures, role-based visibility, and PWA endpoints."""
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.advances.models import CashAdvance
from apps.core.attachments import inbox_items
from apps.dashboard.services import aging, build_dashboard
from apps.invoicing.models import Invoice
from apps.payments.models import Payment
from apps.payments.services import allocate_payment

from tests.test_journal_rules import (  # noqa: F401
    account_types, accounts, journals, customer, supplier, employee, project,
)

D = Decimal


def _user(django_user_model, email, group=None, superuser=False):
    if superuser:
        return django_user_model.objects.create_superuser(email=email, password='x', first_name='A', last_name='B')
    u = django_user_model.objects.create_user(email=email, password='x', first_name='A', last_name='B')
    if group:
        u.groups.add(Group.objects.get_or_create(name=group)[0])
    return u


@pytest.fixture
def data(accounts, journals, customer, employee, project):
    today = timezone.localdate()
    inv_overdue = Invoice.objects.create(project=project, customer=customer, date=today - timedelta(days=50),
                                         due_date=today - timedelta(days=40), description='a', amount=D('1000'))
    inv_current = Invoice.objects.create(project=project, customer=customer, date=today,
                                         due_date=today + timedelta(days=30), description='b', amount=D('500'))
    inv_overdue.post(); inv_current.post()
    pay = Payment.objects.create(direction='inbound', partner=customer, date=today,
                                 account=accounts['cash'], amount=D('400'))
    pay.post()
    allocate_payment(pay, inv_overdue, D('400'))
    adv = CashAdvance.objects.create(project=project, recipient=employee, date=today, purpose='x', amount=D('300'))
    adv.post()
    Invoice.objects.create(project=project, customer=customer, date=today, due_date=today,
                           description='draft', amount=D('70'))
    return locals()


class TestDashboardServices:
    def test_aging_uses_outstanding_after_payments(self, data):
        a = aging(Invoice.objects.all(), timezone.localdate())
        assert a['total'] == D('1100')          # 600 overdue + 500 current
        assert a['overdue'] == D('600')
        buckets = {b['key']: b['amount'] for b in a['buckets']}
        assert buckets['d60'] == D('600') and buckets['current'] == D('500')

    def test_financial_context(self, data, django_user_model):
        ctx = build_dashboard(_user(django_user_model, 'acc@example.com', 'Accountant'))
        assert ctx['show_financials']
        assert ctx['cash']['total'] == D('100')   # +400 received - 300 advance
        assert ctx['advances']['total'] == D('300')
        assert ctx['month']['current']['revenue'] in (D('500'), D('1500'))  # depends on month boundary
        project_row = ctx['projects'][0]
        assert project_row.dash_revenue == D('1500')
        assert project_row.dash_receivable == D('1100')
        texts = [i['text'] for i in ctx['attention']]
        assert any('تأخر في الدفع' in t for t in texts)        # overdue customer
        assert any('لم يُعتمد بعد' in t for t in texts)        # one draft invoice
        overdue = next(i for i in ctx['attention'] if 'تأخر' in i['text'])
        assert overdue['amount'] == D('600')

    def test_data_entry_sees_no_financials(self, data, client, django_user_model):
        client.force_login(_user(django_user_model, 'de@example.com', 'DataEntry'))
        resp = client.get(reverse('dashboard:home'))
        assert resp.status_code == 200
        assert not resp.context['show_financials']
        html = resp.content.decode()
        assert 'المال المتوفر لديك' not in html
        assert 'سجّل مصروفاً' in html  # actions are still there

    def test_dashboard_renders_for_manager(self, data, client, django_user_model):
        client.force_login(_user(django_user_model, 'boss@example.com', superuser=True))
        html = client.get(reverse('dashboard:home')).content.decode()
        for text in ('ماذا تريد أن تفعل؟', 'المال المتوفر لديك', 'لك عند الزبائن', 'يحتاج انتباهك', 'مشاريعك', 'آخر ما سُجّل'):
            assert text in html
        assert 'ربح' in html or 'خسارة' in html or 'لا حركة بعد' in html


class TestPWA:
    def test_manifest(self, client):
        resp = client.get('/manifest.webmanifest')
        assert resp['Content-Type'] == 'application/manifest+json'
        data = json.loads(resp.content)
        assert data['display'] == 'standalone' and data['dir'] == 'rtl'
        assert data['share_target']['action'] == reverse('pwa_share')
        assert any(i.get('purpose') == 'maskable' for i in data['icons'])

    def test_service_worker_never_caches_pages(self, client):
        resp = client.get('/sw.js')
        body = resp.content.decode()
        assert resp['Service-Worker-Allowed'] == '/'
        assert resp['Content-Type'].startswith('application/javascript')
        assert "req.method !== 'GET'" in body and 'OFFLINE_URL' in body
        assert '/offline/' in body

    def test_offline_page_public(self, client):
        assert client.get('/offline/').status_code == 200

    def test_share_target_puts_files_in_inbox(self, client, django_user_model, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        client.force_login(_user(django_user_model, 'pm@example.com', 'DataEntry'))
        client.handler.enforce_csrf_checks = True  # the OS share sheet sends no token
        resp = client.post(reverse('pwa_share'), {
            'title': 'receipt', 'file': SimpleUploadedFile('r.pdf', b'%PDF-1.4\n%%EOF'),
        })
        assert resp.status_code == 302 and resp['Location'] == reverse('core:scan_inbox')
        assert inbox_items().count() == 1

    def test_share_target_requires_login(self, client, db):
        resp = client.post(reverse('pwa_share'), {'file': SimpleUploadedFile('r.pdf', b'%PDF-1.4')})
        assert resp.status_code == 302 and 'login' in resp['Location']
        assert inbox_items().count() == 0
