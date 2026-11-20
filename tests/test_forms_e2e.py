"""
End-to-end walk through EVERY form in the app with the Django test client,
the way a user would: open the form (GET 200), submit valid data (redirect),
attach files where the form allows it, post the document, and finally check
the books still balance.

Runs on SQLite + local files by default, and on PostgreSQL + MinIO (S3)
inside Docker:  docker compose --profile test run --rm test
"""
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO, StringIO

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from PIL import Image

from apps.accounting.models import Account, AccountType, Journal, JournalEntry
from apps.accounting.posting import get_trial_balance
from apps.advances.models import AdvanceReturn, CashAdvance
from apps.core.attachments import attachments_for
from apps.core.models import CompanySettings, Partner
from apps.expenses.models import Expense, ExpenseBatch, PaperReceipt
from apps.invoicing.models import Bill, Invoice
from apps.payments.models import Payment
from apps.projects.models import Project

D = Decimal
TODAY = date.today()
PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


def pdf(name='scan.pdf', extra=b''):
    return SimpleUploadedFile(name, PDF + extra, content_type='application/pdf')


def jpeg(name='photo.jpg', color=(120, 40, 40)):
    out = BytesIO()
    Image.new('RGB', (300, 200), color).save(out, 'JPEG')
    return SimpleUploadedFile(name, out.getvalue(), content_type='image/jpeg')


@pytest.fixture
def books(db, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / 'media'
    call_command('seed_demo', stdout=StringIO())
    return {
        'cash': Account.objects.get(code='1000'),
        'bank': Account.objects.get(code='1010'),
        'materials': Account.objects.get(code='5000'),
        'labor': Account.objects.get(code='5100'),
        'capital': Account.objects.get(code='3000'),
        'customer': Partner.objects.get(code='CUST001'),
        'supplier': Partner.objects.get(code='SUPP001'),
        'employee': Partner.objects.get(code='EMP001'),
        'project': Project.objects.get(code='PRJ001'),
        'project2': Project.objects.get(code='PRJ002'),
        'general': Journal.objects.get(code='GEN'),
    }


@pytest.fixture
def boss(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        email='owner@example.com', password='x', first_name='صاحب', last_name='الشركة')
    client.force_login(user)
    return client


def submit(client, url, data, files=None):
    """GET the form, then POST it. Fails with the form errors if it doesn't redirect."""
    get = client.get(url)
    assert get.status_code == 200, f'GET {url} -> {get.status_code}'
    payload = dict(data)
    if files:
        payload.update(files)
    resp = client.post(url, payload)
    if resp.status_code != 302:
        errors = {}
        ctx = resp.context or {}
        for key in ('form', 'header_form'):
            form = ctx.get(key)
            if form is not None and form.errors:
                errors[key] = form.errors.as_data()
        formset = ctx.get('formset')
        if formset is not None:
            errors['formset'] = [f.errors for f in formset if f.errors] + list(formset.non_form_errors())
        msgs = [str(m) for m in ctx['messages']] if 'messages' in ctx else []
        pytest.fail(f'POST {url} -> {resp.status_code}; errors={errors}; messages={msgs}')
    return resp


def post_doc(client, url_name, *args):
    resp = client.post(reverse(url_name, args=args))
    assert resp.status_code == 302, f'{url_name} -> {resp.status_code}'
    return resp


def files_exist(obj, n):
    atts = list(attachments_for(obj))
    assert len(atts) == n, f'{obj}: expected {n} attachments, got {len(atts)}'
    for att in atts:
        assert default_storage.exists(att.file.name), f'missing in storage: {att.file.name}'
    return atts


# ===========================================================================
class TestEveryForm:
    """One long scenario: a month in the life of the company."""

    def test_full_cycle(self, boss, books):
        b = books
        c = boss

        # --- Master data -------------------------------------------------
        submit(c, reverse('core:partner_create'), {
            'code': 'SUPP900', 'name': 'مورد الرمل', 'type': 'supplier', 'is_active': 'on',
        })
        new_supplier = Partner.objects.get(code='SUPP900')
        submit(c, reverse('core:partner_edit', args=[new_supplier.pk]), {
            'code': 'SUPP900', 'name': 'مورد الرمل والحصى', 'type': 'supplier', 'is_active': 'on',
        })
        new_supplier.refresh_from_db()
        assert new_supplier.name == 'مورد الرمل والحصى'

        submit(c, reverse('projects:create'), {
            'code': 'PRJ900', 'name': 'فيلا الحي الشمالي', 'customer': b['customer'].pk,
            'status': 'active', 'start_date': TODAY, 'budget': '100000',
        })
        project = Project.objects.get(code='PRJ900')
        submit(c, reverse('projects:edit', args=[project.pk]), {
            'code': 'PRJ900', 'name': 'فيلا الحي الشمالي', 'customer': b['customer'].pk,
            'status': 'active', 'start_date': TODAY, 'budget': '120000',
        })

        expense_type = AccountType.objects.get(code='expense')
        submit(c, reverse('accounting:account_create'), {
            'code': '5900', 'name': 'مصروفات الضيافة', 'account_type': expense_type.pk, 'is_active': 'on',
        })
        hospitality = Account.objects.get(code='5900')
        submit(c, reverse('accounting:account_edit', args=[hospitality.pk]), {
            'code': '5900', 'name': 'ضيافة', 'account_type': expense_type.pk, 'is_active': 'on',
        })

        submit(c, reverse('accounting:journal_create'), {
            'code': 'MISC', 'name': 'يومية متنوعة', 'type': 'general', 'is_active': 'on',
        })
        # Re-save every seeded journal unchanged: catches invalid stored choices
        for journal in Journal.objects.all():
            submit(c, reverse('accounting:journal_edit', args=[journal.pk]), {
                'code': journal.code, 'name': journal.name, 'type': journal.type,
                'default_debit_account': journal.default_debit_account_id or '',
                'default_credit_account': journal.default_credit_account_id or '',
                'is_active': 'on',
            })

        submit(c, reverse('core:company_settings'), {
            'name': 'شركة المقاولات', 'currency': 'IQD', 'currency_symbol': 'د.ع',
            'email': 'info@example.com',
        }, files={'logo': jpeg('logo.jpg')})
        company = CompanySettings.get_settings()
        assert company.currency_symbol == 'د.ع'
        assert default_storage.exists(company.logo.name)

        # --- Opening capital: manual journal entry -------------------------
        submit(c, reverse('accounting:entry_create'), {
            'journal': b['general'].pk, 'date': TODAY, 'memo': 'رأس المال',
            'lines-TOTAL_FORMS': '2', 'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '2', 'lines-MAX_NUM_FORMS': '1000',
            'lines-0-account': b['cash'].pk, 'lines-0-debit': '500000', 'lines-0-credit': '0',
            'lines-1-account': b['capital'].pk, 'lines-1-debit': '0', 'lines-1-credit': '500000',
        })
        assert JournalEntry.objects.filter(memo='رأس المال', is_posted=True).exists()

        # --- Customer invoice with attachments ------------------------------
        submit(c, reverse('invoicing:create'), {
            'project': project.pk, 'customer': b['customer'].pk, 'date': TODAY,
            'due_date': TODAY + timedelta(days=30), 'amount': '80000', 'description': 'دفعة أولى',
        }, files={'attachments': [pdf('contract.pdf'), jpeg('site.jpg')]})
        invoice = Invoice.objects.get(project=project)
        files_exist(invoice, 2)
        submit(c, reverse('invoicing:edit', args=[invoice.pk]), {
            'project': project.pk, 'customer': b['customer'].pk, 'date': TODAY,
            'due_date': TODAY + timedelta(days=30), 'amount': '90000', 'description': 'دفعة أولى',
        })
        post_doc(c, 'invoicing:post', invoice.pk)
        invoice.refresh_from_db()
        assert invoice.status == 'posted' and invoice.amount == D('90000')
        assert c.get(reverse('invoicing:print', args=[invoice.pk])).status_code == 200

        # --- Supplier bill ---------------------------------------------------
        submit(c, reverse('bills:create'), {
            'project': project.pk, 'supplier': new_supplier.pk, 'account': b['materials'].pk,
            'date': TODAY, 'due_date': TODAY + timedelta(days=15), 'vendor_reference': 'V-77',
            'amount': '20000', 'description': 'رمل وحصى',
        }, files={'attachments': [pdf('supplier-invoice.pdf')]})
        bill = Bill.objects.get(vendor_reference='V-77')
        files_exist(bill, 1)
        submit(c, reverse('bills:edit', args=[bill.pk]), {
            'project': project.pk, 'supplier': new_supplier.pk, 'account': b['materials'].pk,
            'date': TODAY, 'due_date': TODAY + timedelta(days=15), 'vendor_reference': 'V-77',
            'amount': '20000', 'description': 'رمل وحصى (معدل)',
        })
        post_doc(c, 'bills:post', bill.pk)

        # --- Payments in / out + allocation ---------------------------------
        submit(c, reverse('payments:receive'), {
            'direction': 'inbound', 'partner': b['customer'].pk, 'date': TODAY,
            'account': b['bank'].pk, 'amount': '50000', 'reference': 'TRF-1',
        }, files={'attachments': [pdf('bank-slip.pdf')]})
        pay_in = Payment.objects.get(reference='TRF-1')
        files_exist(pay_in, 1)
        post_doc(c, 'payments:post', pay_in.pk)
        c.post(reverse('payments:allocate', args=[pay_in.pk]),
               {'doc_type': 'invoice', 'doc_id': invoice.pk, 'amount': '50000'})
        assert invoice.amount_remaining == D('40000')

        submit(c, reverse('payments:pay'), {
            'direction': 'outbound', 'partner': new_supplier.pk, 'date': TODAY,
            'account': b['cash'].pk, 'amount': '20000', 'reference': 'CHQ-9',
        })
        pay_out = Payment.objects.get(reference='CHQ-9')
        submit(c, reverse('payments:edit', args=[pay_out.pk]), {
            'direction': 'outbound', 'partner': new_supplier.pk, 'date': TODAY,
            'account': b['cash'].pk, 'amount': '20000', 'reference': 'CHQ-9', 'memo': 'نقداً',
        })
        post_doc(c, 'payments:post', pay_out.pk)
        c.post(reverse('payments:allocate', args=[pay_out.pk]),
               {'doc_type': 'bill', 'doc_id': bill.pk, 'amount': '20000'})
        assert bill.is_paid

        # --- Cash advance -> expenses (single + lines document) -> return ---
        submit(c, reverse('advances:create'), {
            'project': project.pk, 'recipient': b['employee'].pk, 'date': TODAY,
            'amount': '10000', 'purpose': 'مشتريات الموقع',
        }, files={'attachments': [jpeg('handover.jpg')]})
        advance = CashAdvance.objects.get(purpose='مشتريات الموقع')
        files_exist(advance, 1)
        submit(c, reverse('advances:edit', args=[advance.pk]), {
            'project': project.pk, 'recipient': b['employee'].pk, 'date': TODAY,
            'amount': '12000', 'purpose': 'مشتريات الموقع',
        })
        post_doc(c, 'advances:post', advance.pk)

        submit(c, reverse('expenses:create'), {
            'date': TODAY, 'project': project.pk, 'advance': advance.pk, 'account': b['labor'].pk,
            'amount': '3000', 'description': 'أجور عمال يومية', 'receipt_number': 'R-1',
            'combine_images': '1',
        }, files={'attachments': [jpeg('r1.jpg'), jpeg('r1b.jpg', (1, 2, 3))]})
        expense = Expense.objects.get(receipt_number='R-1')
        atts = files_exist(expense, 1)  # two photos merged into one PDF
        assert atts[0].original_filename.endswith('.pdf')
        submit(c, reverse('expenses:edit', args=[expense.pk]), {
            'date': TODAY, 'project': project.pk, 'advance': advance.pk, 'account': b['labor'].pk,
            'amount': '3500', 'description': 'أجور عمال يومية', 'receipt_number': 'R-1',
        })
        post_doc(c, 'expenses:post', expense.pk)

        submit(c, reverse('advances:expense_lines', args=[advance.pk]), {
            'date': TODAY, 'memo': 'فواتير الأسبوع',
            'lines-TOTAL_FORMS': '2', 'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '0', 'lines-MAX_NUM_FORMS': '1000',
            'lines-0-date': TODAY, 'lines-0-project': project.pk, 'lines-0-account': b['materials'].pk,
            'lines-0-description': 'إسمنت', 'lines-0-receipt_number': 'R-2', 'lines-0-amount': '4000',
            'lines-1-date': TODAY, 'lines-1-project': b['project2'].pk, 'lines-1-account': hospitality.pk,
            'lines-1-description': 'ضيافة', 'lines-1-receipt_number': 'R-3', 'lines-1-amount': '500',
        }, files={'attachments': [pdf('week.pdf')]})
        batch = ExpenseBatch.objects.get(memo='فواتير الأسبوع')
        files_exist(batch, 1)
        post_doc(c, 'expenses:batch_post', batch.pk)

        submit(c, reverse('advances:return_create_for', args=[advance.pk]), {
            'advance': advance.pk, 'date': TODAY, 'amount': '4000', 'notes': 'إرجاع الباقي',
        })
        ret = AdvanceReturn.objects.get(advance=advance)
        post_doc(c, 'advances:return_post', ret.pk)
        advance.refresh_from_db()
        assert advance.remaining == D('0.00')     # 12000 - 3500 - 4500 - 4000
        post_doc(c, 'advances:close', advance.pk)
        advance.refresh_from_db()
        assert advance.status == 'closed'

        # --- Company-level expense (no project, paid from cash) -------------
        submit(c, reverse('expenses:create'), {
            'date': TODAY, 'account': hospitality.pk, 'amount': '250', 'description': 'قهوة المكتب',
        })
        office = Expense.objects.get(description='قهوة المكتب')
        post_doc(c, 'expenses:post', office.pk)
        office.refresh_from_db()
        assert office.status == 'posted'

        # --- Paper receipt register ------------------------------------------
        submit(c, reverse('expenses:receipt_create'), {
            'vendor_name': 'محل العدد', 'date': TODAY, 'amount': '120',
            'received_from': b['employee'].pk,
        })
        assert PaperReceipt.objects.filter(vendor_name='محل العدد').exists()

        # --- Users ------------------------------------------------------------
        submit(c, reverse('accounts:user_create'), {
            'email': 'clerk@example.com', 'first_name': 'موظف', 'last_name': 'جديد', 'is_active': 'on',
            'password': 'Str0ng-Passw0rd!', 'password_confirm': 'Str0ng-Passw0rd!', 'role': 'DataEntry',
        })
        from django.contrib.auth import get_user_model
        clerk = get_user_model().objects.get(email='clerk@example.com')
        submit(c, reverse('accounts:user_edit', args=[clerk.pk]), {
            'email': 'clerk@example.com', 'first_name': 'موظف', 'last_name': 'المكتب', 'is_active': 'on',
            'role': 'DataEntry',
        })
        submit(c, reverse('accounts:user_password', args=[clerk.pk]), {
            'password': 'An0ther-Passw0rd!', 'password_confirm': 'An0ther-Passw0rd!',
        })
        clerk.refresh_from_db()
        assert clerk.check_password('An0ther-Passw0rd!')

        # --- Reports render and the books balance ----------------------------
        for name in ('trial_balance', 'income_statement', 'balance_sheet', 'receivables', 'payables'):
            assert c.get(reverse(f'accounting:{name}')).status_code == 200
        ledger = c.get(reverse('accounting:ledger'), {'account': b['cash'].pk, 'date_from': TODAY})
        assert ledger.status_code == 200
        assert c.get(reverse('dashboard:home')).status_code == 200
        assert c.get(reverse('projects:detail', args=[project.pk])).status_code == 200
        assert get_trial_balance()['is_balanced']

        # --- Cancelling a posted document creates a reversal -----------------
        post_doc(c, 'payments:deallocate', pay_in.pk, pay_in.allocations.first().pk)
        post_doc(c, 'payments:cancel', pay_in.pk)
        pay_in.refresh_from_db()
        assert pay_in.status == 'cancelled' and pay_in.journal_entry.is_reversed
        assert get_trial_balance()['is_balanced']


class TestDataEntryRole:
    def test_clerk_can_draft_but_not_post(self, client, books, django_user_model):
        from django.contrib.auth.models import Group
        clerk = django_user_model.objects.create_user(
            email='de@example.com', password='x', first_name='م', last_name='د')
        clerk.groups.add(Group.objects.get(name='DataEntry'))
        client.force_login(clerk)

        submit(client, reverse('expenses:create'), {
            'date': TODAY, 'project': books['project'].pk, 'account': books['materials'].pk,
            'amount': '100', 'description': 'مسامير',
        }, files={'attachments': [jpeg('nails.jpg')]})
        expense = Expense.objects.get(description='مسامير')
        files_exist(expense, 1)

        client.post(reverse('expenses:post', args=[expense.pk]))
        expense.refresh_from_db()
        assert expense.status == 'draft'
        assert client.get(reverse('accounting:trial_balance')).status_code == 302
        assert client.get(reverse('accounts:users')).status_code == 302


class TestPdfReports:
    def test_invoice_and_project_pdf(self, boss, books):
        try:
            import weasyprint  # noqa: F401 - needs pango/cairo (installed in the Docker image)
        except OSError as exc:
            pytest.skip(f'weasyprint system libraries missing: {exc}')
        inv = Invoice.objects.first()
        resp = boss.get(reverse('invoicing:pdf', args=[inv.pk]))
        assert resp.status_code == 200 and resp['Content-Type'] == 'application/pdf'
        resp = boss.get(reverse('projects:report_pdf', args=[books['project'].pk]))
        assert resp.status_code == 200 and resp['Content-Type'] == 'application/pdf'
