"""
Statements (customer / supplier / سلف), quick create-edit of partners from
inside forms, "add to this project" prefill + return, and the PDF documents.
"""
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounting.models import Account
from apps.advances.models import AdvanceReturn, CashAdvance
from apps.core.models import Partner
from apps.expenses.models import Expense
from apps.invoicing.models import Bill, Invoice
from apps.payments.models import Payment
from apps.projects.models import Project
from apps.reports.statements import advance_statement, partner_statement

D = Decimal
TODAY = date.today()


@pytest.fixture
def books(db, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / 'media'
    call_command('seed_demo', stdout=StringIO())
    return {
        'cash': Account.objects.get(code='1000'),
        'materials': Account.objects.get(code='5000'),
        'project': Project.objects.get(code='PRJ001'),
    }


@pytest.fixture
def boss(client, django_user_model):
    user = django_user_model.objects.create_superuser(email='owner@example.com', password='x')
    client.force_login(user)
    client.user = user
    return client


def _invoice(books, customer, amount, day, post=True):
    inv = Invoice.objects.create(project=books['project'], customer=customer, date=day,
                                 due_date=day + timedelta(days=30), amount=D(amount),
                                 amount_base=D(amount), description='أعمال')
    if post:
        inv.post()
    return inv


def _payment(books, partner, amount, day, direction='inbound'):
    pay = Payment.objects.create(direction=direction, partner=partner, date=day, account=books['cash'],
                                 amount=D(amount), amount_base=D(amount))
    pay.post()
    return pay


# --------------------------------------------------------------------------- statements

class TestPartnerStatement:
    def test_customer_running_balance_and_cancelled_documents(self, books):
        customer = Partner.objects.create(name='عميل الكشف', type='customer')
        _invoice(books, customer, '1000.00', TODAY - timedelta(days=10))
        _payment(books, customer, '400.00', TODAY - timedelta(days=5))
        cancelled = _invoice(books, customer, '999.00', TODAY - timedelta(days=4))
        cancelled.cancel()
        _invoice(books, customer, '50.00', TODAY, post=False)          # draft: not in the books

        st = partner_statement(customer)
        assert [r.debit for r in st.rows] == [D('1000.00'), D('0.00')]
        assert [r.balance for r in st.rows] == [D('1000.00'), D('600.00')]
        assert st.closing == D('600.00')
        assert st.closing_meaning == 'مستحق لنا على العميل'

    def test_opening_balance_from_date(self, books):
        customer = Partner.objects.create(name='عميل افتتاحي', type='customer')
        _invoice(books, customer, '300.00', TODAY - timedelta(days=40))
        _invoice(books, customer, '200.00', TODAY - timedelta(days=2))
        st = partner_statement(customer, date_from=TODAY - timedelta(days=7), date_to=TODAY)
        assert st.opening == D('300.00')
        assert len(st.rows) == 1
        assert st.closing == D('500.00')

    def test_supplier_balance_is_what_we_owe(self, books):
        supplier = Partner.objects.create(name='مورد الكشف', type='supplier')
        bill = Bill.objects.create(supplier=supplier, project=books['project'], account=books['materials'],
                                   date=TODAY, due_date=TODAY, amount=D('800.00'), amount_base=D('800.00'))
        bill.post()
        _payment(books, supplier, '300.00', TODAY, direction='outbound')
        st = partner_statement(supplier)
        assert st.closing == D('500.00')
        assert st.closing_meaning == 'مستحق للمورد علينا'

    def test_employee_advance_statement_matches_settlement(self, books):
        employee = Partner.objects.create(name='موظف السلف', type='employee')
        adv = CashAdvance.objects.create(project=books['project'], recipient=employee, date=TODAY,
                                         amount=D('1000.00'), amount_base=D('1000.00'), purpose='مواد')
        adv.post()
        exp = Expense.objects.create(advance=adv, project=books['project'], account=books['materials'],
                                     date=TODAY, amount=D('350.00'), amount_base=D('350.00'), description='اسمنت')
        exp.post()
        ret = AdvanceReturn.objects.create(advance=adv, date=TODAY, amount=D('150.00'), amount_base=D('150.00'))
        ret.post()

        st = partner_statement(employee)
        assert st.closing == adv.remaining == D('500.00')
        data = advance_statement(adv)
        assert list(data['expenses']) == [exp]
        assert data['total_returned'] == D('150.00')


# --------------------------------------------------------------------------- statement pages + PDFs

class TestStatementPages:
    def test_screen_and_pdf(self, books, boss):
        customer = Partner.objects.create(name='عميل الطباعة', type='customer')
        _invoice(books, customer, '1234.50', TODAY)
        resp = boss.get(reverse('reports:partner_statement', args=[customer.pk]))
        assert resp.status_code == 200
        assert '1,234.50' in resp.content.decode()
        pdf = boss.get(reverse('reports:partner_statement_pdf', args=[customer.pk]))
        assert pdf.status_code == 200 and pdf['Content-Type'] == 'application/pdf'
        assert pdf.content.startswith(b'%PDF')
        assert boss.get(reverse('reports:statements') + '?type=employee').status_code == 200

    def test_data_entry_cannot_see_statements(self, books, client, django_user_model):
        from django.contrib.auth.models import Group
        clerk = django_user_model.objects.create_user(email='clerk-statements@example.com', password='x')
        clerk.groups.add(Group.objects.get_or_create(name='DataEntry')[0])
        client.force_login(clerk)
        customer = Partner.objects.create(name='عميل', type='customer')
        resp = client.get(reverse('reports:partner_statement', args=[customer.pk]))
        assert resp.status_code == 302

    def test_document_pdfs(self, books, boss):
        customer = Partner.objects.create(name='عميل', type='customer')
        employee = Partner.objects.create(name='موظف', type='employee')
        inv = _invoice(books, customer, '500.00', TODAY)
        pay = _payment(books, customer, '100.00', TODAY)
        adv = CashAdvance.objects.create(project=books['project'], recipient=employee, date=TODAY,
                                         amount=D('200.00'), amount_base=D('200.00'), purpose='نقل')
        adv.post()
        for url in [reverse('invoicing:pdf', args=[inv.pk]), reverse('payments:pdf', args=[pay.pk]),
                    reverse('reports:advance_statement_pdf', args=[adv.pk]),
                    reverse('projects:report_pdf', args=[books['project'].pk])]:
            resp = boss.get(url)
            assert resp.status_code == 200, url
            assert resp.content.startswith(b'%PDF'), url


# --------------------------------------------------------------------------- quick create / edit

class TestQuickCreate:
    def test_partner_code_is_generated(self, db):
        assert Partner.objects.create(name='أ', type='customer').code == 'CUS-0001'
        assert Partner.objects.create(name='ب', type='customer').code == 'CUS-0002'
        assert Partner.objects.create(name='ج', type='supplier').code == 'SUP-0001'

    def test_create_returns_json_and_type_is_fixed(self, boss):
        url = reverse('core:partner_quick_create') + '?type=customer'
        assert boss.get(url).status_code == 200
        resp = boss.post(url, {'name': 'عميل سريع', 'type': 'supplier', 'phone': '0500'})
        assert resp.status_code == 200
        data = resp.json()
        partner = Partner.objects.get(pk=data['id'])
        assert partner.type == 'customer'           # ?type= wins over the posted value
        assert partner.created_by == boss.user
        assert data['label'] == str(partner)

    def test_invalid_returns_form_with_400(self, boss):
        resp = boss.post(reverse('core:partner_quick_create'), {'name': '', 'type': 'customer'})
        assert resp.status_code == 400
        assert b'form-error' in resp.content

    def test_edit_keeps_type(self, boss):
        partner = Partner.objects.create(name='قديم', type='supplier')
        resp = boss.post(reverse('core:partner_quick_edit', args=[partner.pk]),
                         {'name': 'جديد', 'type': 'customer'})
        assert resp.json()['created'] is False
        partner.refresh_from_db()
        assert (partner.name, partner.type) == ('جديد', 'supplier')

    def test_forms_carry_the_quick_buttons(self, books, boss):
        for url in [reverse('expenses:create'), reverse('invoicing:create'), reverse('bills:create'),
                    reverse('advances:create'), reverse('payments:receive'), reverse('projects:create')]:
            assert b'data-quick-create' in boss.get(url).content, url

    def test_expense_can_be_paid_to_a_new_customer(self, books, boss):
        customer = Partner.objects.create(name='عميل في مصروف', type='customer')
        resp = boss.post(reverse('expenses:create'), {
            'date': TODAY, 'account': books['materials'].pk, 'partner': customer.pk,
            'amount': '10.00', 'description': 'x',
        })
        assert resp.status_code == 302
        assert Expense.objects.filter(partner=customer).exists()


# --------------------------------------------------------------------------- project page actions

class TestProjectActions:
    def test_project_page_links_prefill_and_return(self, books, boss):
        project = books['project']
        page = boss.get(reverse('projects:detail', args=[project.pk])).content.decode()
        assert f'?project={project.pk}&amp;next=' in page

        form = boss.get(reverse('invoicing:create') + f'?project={project.pk}')
        assert form.context['form'].initial['project'] == project
        assert form.context['form'].initial['customer'] == project.customer

        back = reverse('projects:detail', args=[project.pk])
        resp = boss.post(reverse('expenses:create') + f'?project={project.pk}&next={back}', {
            'date': TODAY, 'project': project.pk, 'account': books['materials'].pk,
            'amount': '25.00', 'description': 'من صفحة المشروع',
        })
        assert resp.status_code == 302 and resp['Location'] == back

    def test_completed_project_still_prefilled(self, books, boss):
        """Forms opened from a completed project's page keep that project selected."""
        project = books['project']
        project.status = 'completed'
        project.save()
        selected = f'<option value="{project.pk}" selected>'
        for name in ['expenses:create', 'invoicing:create', 'bills:create', 'advances:create']:
            html = boss.get(reverse(name) + f'?project={project.pk}').content.decode()
            assert selected in html, name
        html = boss.get(reverse('invoicing:create') + f'?project={project.pk}').content.decode()
        assert f'<option value="{project.customer.pk}" selected>' in html

        resp = boss.post(reverse('expenses:create') + f'?project={project.pk}', {
            'date': TODAY, 'project': project.pk, 'account': books['materials'].pk,
            'amount': '12.00', 'description': 'مشروع مكتمل',
        })
        assert resp.status_code == 302
        assert Expense.objects.filter(project=project, description='مشروع مكتمل').exists()

        # A plain "new expense" form still lists active projects only
        form = boss.get(reverse('expenses:create')).context['form']
        assert project not in form.fields['project'].queryset

    def test_next_must_be_on_this_site(self, books, boss):
        resp = boss.post(reverse('expenses:create') + '?next=https://evil.example/', {
            'date': TODAY, 'account': books['materials'].pk, 'amount': '5.00', 'description': 'x',
        })
        assert resp.status_code == 302
        assert 'evil' not in resp['Location']
