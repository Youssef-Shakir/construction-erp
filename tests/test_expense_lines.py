"""
Tests for bulk expense-line entry against a cash advance
(advances:expense_lines) — adding several expenses "كفقرات" in one submit,
each with its own optional project and receipt number.
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from django.urls import reverse

from apps.accounting.models import AccountType, Account, Journal
from apps.accounting.posting import PostingError
from apps.core.models import Partner
from apps.projects.models import Project
from apps.advances.models import CashAdvance
from apps.expenses.models import Expense, ExpenseBatch


@pytest.fixture
def account_types(db):
    types = [
        ('asset', 'الأصول', 'debit', 'balance_sheet', 1),
        ('expense', 'المصروفات', 'debit', 'income_statement', 5),
    ]
    created = {}
    for code, name, normal_balance, report_section, order in types:
        created[code] = AccountType.objects.create(
            code=code, name=name, normal_balance=normal_balance,
            report_section=report_section, order=order
        )
    return created


@pytest.fixture
def accounts(db, account_types):
    return {
        'cash': Account.objects.create(code='1000', name='النقدية', account_type=account_types['asset']),
        'advances': Account.objects.create(
            code='1200', name='سلف الموظفين', account_type=account_types['asset'], is_control=True
        ),
        'expense': Account.objects.create(code='5000', name='مصروفات المواد', account_type=account_types['expense']),
    }


@pytest.fixture
def journals(db):
    return {'cash': Journal.objects.create(code='CASH', name='يومية النقدية', type='cash')}


@pytest.fixture
def employee(db):
    return Partner.objects.create(code='EMP001', name='أحمد محمد', type='employee')


@pytest.fixture
def customer(db):
    return Partner.objects.create(code='CUST001', name='شركة البناء', type='customer')


@pytest.fixture
def project(db, customer):
    return Project.objects.create(
        code='PRJ001', name='مشروع البرج السكني', customer=customer,
        start_date=date.today() - timedelta(days=30),
        budget=Decimal('500000.00'), status='active'
    )


@pytest.fixture
def other_project(db, customer):
    return Project.objects.create(
        code='PRJ002', name='مشروع الفيلا', customer=customer,
        start_date=date.today() - timedelta(days=10),
        budget=Decimal('200000.00'), status='active'
    )


@pytest.fixture
def posted_advance(db, accounts, journals, employee, project):
    advance = CashAdvance.objects.create(
        project=project,
        recipient=employee,
        date=date.today(),
        purpose='شراء مواد بناء',
        amount=Decimal('10000.00'),
        amount_base=Decimal('10000.00'),
    )
    advance.post()
    return advance


def _formset_data(rows, total_forms=3):
    """Build POST data for the header form + ExpenseLineFormSet given a list of row dicts."""
    data = {
        'date': str(date.today()),
        'memo': '',
        'lines-TOTAL_FORMS': str(total_forms),
        'lines-INITIAL_FORMS': '0',
        'lines-MIN_NUM_FORMS': '0',
        'lines-MAX_NUM_FORMS': '1000',
    }
    for i in range(total_forms):
        prefix = f'lines-{i}'
        if i < len(rows):
            row = rows[i]
            data[f'{prefix}-date'] = str(row.get('date', date.today()))
            data[f'{prefix}-project'] = str(row['project'].pk) if row.get('project') else ''
            data[f'{prefix}-account'] = str(row['account'].pk) if row.get('account') else ''
            data[f'{prefix}-description'] = row.get('description', '')
            data[f'{prefix}-receipt_number'] = row.get('receipt_number', '')
            data[f'{prefix}-amount'] = str(row['amount']) if row.get('amount') is not None else ''
        else:
            data[f'{prefix}-date'] = ''
            data[f'{prefix}-project'] = ''
            data[f'{prefix}-account'] = ''
            data[f'{prefix}-description'] = ''
            data[f'{prefix}-receipt_number'] = ''
            data[f'{prefix}-amount'] = ''
    return data


class TestBulkExpenseLines:
    """Adding multiple expense lines against an advance in one submit."""

    def test_get_renders_form(self, client_logged_in, posted_advance):
        url = reverse('advances:expense_lines', args=[posted_advance.pk])
        response = client_logged_in.get(url)
        assert response.status_code == 200
        assert 'formset' in response.context

    def test_creates_multiple_draft_expenses_across_projects(
        self, client_logged_in, posted_advance, other_project, accounts
    ):
        url = reverse('advances:expense_lines', args=[posted_advance.pk])
        rows = [
            {
                'project': posted_advance.project,
                'account': accounts['expense'],
                'description': 'حديد تسليح',
                'receipt_number': 'R-001',
                'amount': Decimal('1500.00'),
            },
            {
                'project': other_project,
                'account': accounts['expense'],
                'description': 'أسمنت لمشروع آخر',
                'receipt_number': 'R-002',
                'amount': Decimal('900.00'),
            },
            {
                # No project -> defaults to advance's project
                'account': accounts['expense'],
                'description': 'نقل مواد',
                'receipt_number': '',
                'amount': Decimal('300.00'),
            },
        ]
        response = client_logged_in.post(url, _formset_data(rows), follow=True)

        assert response.status_code == 200
        assert Expense.objects.count() == 3

        # One document (ExpenseBatch) groups all three lines
        assert ExpenseBatch.objects.count() == 1
        batch = ExpenseBatch.objects.get()
        assert batch.advance == posted_advance
        assert batch.status == 'draft'
        assert batch.line_count == 3
        assert batch.total_amount == Decimal('2700.00')
        assert set(Expense.objects.values_list('batch_id', flat=True)) == {batch.pk}

        by_receipt = {e.receipt_number: e for e in Expense.objects.all()}
        assert by_receipt['R-001'].project == posted_advance.project
        assert by_receipt['R-002'].project == other_project
        assert by_receipt['R-002'].amount == Decimal('900.00')

        no_receipt = Expense.objects.exclude(receipt_number__in=['R-001', 'R-002']).get()
        assert no_receipt.project == posted_advance.project

        # All created as drafts - posting is a separate, permission-gated step
        assert all(e.status == 'draft' for e in Expense.objects.all())

    def test_blank_rows_are_ignored(self, client_logged_in, posted_advance, accounts):
        url = reverse('advances:expense_lines', args=[posted_advance.pk])
        rows = [
            {
                'account': accounts['expense'],
                'description': 'فقرة واحدة فقط',
                'amount': Decimal('100.00'),
            },
        ]
        response = client_logged_in.post(url, _formset_data(rows), follow=True)

        assert response.status_code == 200
        assert Expense.objects.count() == 1

    def test_incomplete_row_is_rejected_without_saving_anything(
        self, client_logged_in, posted_advance, accounts
    ):
        """A row missing a required field blocks the whole batch (all-or-nothing)."""
        url = reverse('advances:expense_lines', args=[posted_advance.pk])
        rows = [
            {
                'account': accounts['expense'],
                'description': 'فقرة صحيحة',
                'amount': Decimal('100.00'),
            },
            {
                # Missing account -> invalid row
                'description': 'فقرة ناقصة',
                'amount': Decimal('50.00'),
            },
        ]
        response = client_logged_in.post(url, _formset_data(rows), follow=True)

        assert response.status_code == 200
        assert Expense.objects.count() == 0

    def test_requires_posted_advance(self, client_logged_in, accounts, employee, project):
        draft_advance = CashAdvance.objects.create(
            project=project,
            recipient=employee,
            date=date.today(),
            purpose='سلفة مسودة',
            amount=Decimal('5000.00'),
            amount_base=Decimal('5000.00'),
        )
        url = reverse('advances:expense_lines', args=[draft_advance.pk])
        response = client_logged_in.get(url, follow=True)

        assert response.status_code == 200
        assert Expense.objects.count() == 0


class TestExpenseBatchPosting:
    """Posting a batch records every line as ONE journal entry."""

    def _make_batch(self, advance, accounts, amounts_and_projects):
        batch = ExpenseBatch.objects.create(
            advance=advance,
            date=date.today(),
        )
        for amount, project in amounts_and_projects:
            Expense.objects.create(
                date=date.today(),
                project=project,
                advance=advance,
                batch=batch,
                account=accounts['expense'],
                description='فقرة اختبار',
                amount=amount,
                amount_base=amount,
            )
        return batch

    def test_post_creates_a_single_balanced_entry(
        self, posted_advance, other_project, accounts
    ):
        batch = self._make_batch(posted_advance, accounts, [
            (Decimal('1000.00'), posted_advance.project),
            (Decimal('500.00'), other_project),
            (Decimal('250.00'), posted_advance.project),
        ])

        entry = batch.post()

        assert batch.status == 'posted'
        assert batch.journal_entry_id == entry.pk

        # One debit line per expense + one aggregated credit line
        lines = list(entry.lines.all())
        assert len(lines) == 4
        debit_lines = [l for l in lines if l.debit > 0]
        credit_lines = [l for l in lines if l.credit > 0]
        assert len(debit_lines) == 3
        assert len(credit_lines) == 1
        assert credit_lines[0].credit == Decimal('1750.00')
        assert credit_lines[0].partner == posted_advance.recipient
        assert sum(l.debit for l in debit_lines) == credit_lines[0].credit
        assert entry.is_balanced
        assert entry.is_posted

        # Every line's expense flips to posted and settlement reflects it
        assert Expense.objects.filter(batch=batch, status='posted').count() == 3
        assert posted_advance.total_expenses == Decimal('1750.00')
        assert posted_advance.project.total_expenses == Decimal('1250.00')
        assert other_project.total_expenses == Decimal('500.00')

    def test_cannot_post_empty_batch(self, posted_advance):
        batch = ExpenseBatch.objects.create(advance=posted_advance, date=date.today())
        with pytest.raises(PostingError):
            batch.post()

    def test_cannot_exceed_advance_remaining(self, posted_advance, accounts):
        batch = self._make_batch(posted_advance, accounts, [
            (Decimal('9000.00'), posted_advance.project),
            (Decimal('5000.00'), posted_advance.project),
        ])
        with pytest.raises(PostingError):
            batch.post()

    def test_lines_cannot_be_posted_or_cancelled_individually(self, posted_advance, accounts):
        batch = self._make_batch(posted_advance, accounts, [
            (Decimal('100.00'), posted_advance.project),
        ])
        line = batch.lines.get()
        with pytest.raises(PostingError):
            line.post()

        batch.post()
        line.refresh_from_db()
        with pytest.raises(PostingError):
            line.cancel()

    def test_cancel_reverses_the_single_entry_and_all_lines(self, posted_advance, accounts):
        batch = self._make_batch(posted_advance, accounts, [
            (Decimal('300.00'), posted_advance.project),
            (Decimal('200.00'), posted_advance.project),
        ])
        batch.post()

        batch.cancel()

        assert batch.status == 'cancelled'
        assert batch.journal_entry.is_reversed
        assert Expense.objects.filter(batch=batch, status='cancelled').count() == 2
        assert posted_advance.total_expenses == Decimal('0.00')
