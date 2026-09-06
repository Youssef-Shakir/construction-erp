"""
Tests for the eight journal generation rules.

The rules are:
1. Cash advance to PM: Debit Advances to PMs, Credit Cash
2. PM expense against advance: Debit Expense, Credit Advances to PMs
3. Cash returned by PM: Debit Cash, Credit Advances to PMs
4. Customer invoice: Debit AR, Credit Revenue
5. Supplier bill: Debit Expense, Credit AP
6. Payment received: Debit Cash/Bank, Credit AR
7. Payment made: Debit AP, Credit Cash/Bank
8. Direct expense: Debit Expense, Credit Cash/Bank
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from apps.accounting.models import AccountType, Account, Journal
from apps.core.models import Partner
from apps.projects.models import Project
from apps.advances.models import CashAdvance, AdvanceReturn
from apps.expenses.models import Expense
from apps.invoicing.models import Invoice, Bill
from apps.payments.models import Payment


@pytest.fixture
def account_types(db):
    """Create standard account types."""
    types = [
        ('asset', 'الأصول', 'debit', 'balance_sheet', 1),
        ('liability', 'الخصوم', 'credit', 'balance_sheet', 2),
        ('equity', 'حقوق الملكية', 'credit', 'balance_sheet', 3),
        ('revenue', 'الإيرادات', 'credit', 'income_statement', 4),
        ('expense', 'المصروفات', 'debit', 'income_statement', 5),
    ]
    created = {}
    for code, name, normal_balance, report_section, order in types:
        created[code] = AccountType.objects.create(
            code=code,
            name=name,
            normal_balance=normal_balance,
            report_section=report_section,
            order=order
        )
    return created


@pytest.fixture
def accounts(db, account_types):
    """Create chart of accounts."""
    return {
        'cash': Account.objects.create(
            code='1000', name='النقدية', account_type=account_types['asset']
        ),
        'bank': Account.objects.create(
            code='1010', name='البنك', account_type=account_types['asset']
        ),
        'ar': Account.objects.create(
            code='1100', name='العملاء', account_type=account_types['asset'], is_control=True
        ),
        'advances': Account.objects.create(
            code='1200', name='سلف الموظفين', account_type=account_types['asset'], is_control=True
        ),
        'ap': Account.objects.create(
            code='2000', name='الموردين', account_type=account_types['liability'], is_control=True
        ),
        'revenue': Account.objects.create(
            code='4000', name='إيرادات المشاريع', account_type=account_types['revenue']
        ),
        'expense': Account.objects.create(
            code='5000', name='مصروفات المواد', account_type=account_types['expense']
        ),
    }


@pytest.fixture
def journals(db):
    """Create journals."""
    return {
        'cash': Journal.objects.create(code='CASH', name='يومية النقدية', type='cash'),
        'sales': Journal.objects.create(code='SALE', name='يومية المبيعات', type='sale'),
        'purchase': Journal.objects.create(code='PURCH', name='يومية المشتريات', type='purchase'),
        'general': Journal.objects.create(code='GEN', name='القيود العامة', type='general'),
    }


@pytest.fixture
def customer(db):
    """Create a customer partner."""
    return Partner.objects.create(
        code='CUST001',
        name='شركة البناء الحديث',
        type='customer'
    )


@pytest.fixture
def supplier(db):
    """Create a supplier partner."""
    return Partner.objects.create(
        code='SUPP001',
        name='مصنع الأسمنت الوطني',
        type='supplier'
    )


@pytest.fixture
def employee(db):
    """Create an employee partner."""
    return Partner.objects.create(
        code='EMP001',
        name='أحمد محمد',
        type='employee'
    )


@pytest.fixture
def project(db, customer):
    """Create a project."""
    return Project.objects.create(
        code='PRJ001',
        name='مشروع البرج السكني',
        customer=customer,
        start_date=date.today() - timedelta(days=30),
        budget=Decimal('500000.00'),
        status='active'
    )


class TestRule1CashAdvanceToPM:
    """Test Rule 1: Cash advance to PM."""

    def test_cash_advance_creates_correct_journal_entry(
        self, accounts, journals, employee, project
    ):
        """
        Cash advance to PM:
        - Debit: Advances to Project Managers (partner=PM, project)
        - Credit: Cash
        """
        advance = CashAdvance.objects.create(
            project=project,
            recipient=employee,
            date=date.today(),
            purpose='شراء مواد بناء',
            amount=Decimal('10000.00'),
            amount_base=Decimal('10000.00'),
        )

        advance.post()

        # Verify entry was created
        assert advance.journal_entry is not None
        assert advance.status == 'posted'

        # Check journal entry lines
        lines = advance.journal_entry.lines.all()
        assert lines.count() == 2

        # Check debit to advances account
        debit_line = lines.get(debit__gt=0)
        assert debit_line.account.code == '1200'  # Advances to PMs
        assert debit_line.debit == Decimal('10000.00')
        assert debit_line.partner == employee
        assert debit_line.project == project

        # Check credit to cash account
        credit_line = lines.get(credit__gt=0)
        assert credit_line.account.code == '1000'  # Cash
        assert credit_line.credit == Decimal('10000.00')


class TestRule2PMExpenseAgainstAdvance:
    """Test Rule 2: PM expense against advance."""

    def test_expense_against_advance_creates_correct_journal_entry(
        self, accounts, journals, employee, project
    ):
        """
        PM expense against advance:
        - Debit: Expense account (project)
        - Credit: Advances to PMs (partner=PM)
        """
        # First create and post an advance
        advance = CashAdvance.objects.create(
            project=project,
            recipient=employee,
            date=date.today(),
            purpose='شراء مواد بناء',
            amount=Decimal('10000.00'),
            amount_base=Decimal('10000.00'),
        )
        advance.post()

        # Create expense against the advance
        expense = Expense.objects.create(
            date=date.today(),
            project=project,
            advance=advance,
            account=accounts['expense'],
            description='شراء حديد تسليح',
            amount=Decimal('5000.00'),
            amount_base=Decimal('5000.00'),
        )
        expense.post()

        # Verify entry was created
        assert expense.journal_entry is not None
        assert expense.status == 'posted'

        # Check journal entry lines
        lines = expense.journal_entry.lines.all()
        assert lines.count() == 2

        # Check debit to expense account
        debit_line = lines.get(debit__gt=0)
        assert debit_line.account.code == '5000'  # Expense
        assert debit_line.debit == Decimal('5000.00')
        assert debit_line.project == project

        # Check credit to advances account
        credit_line = lines.get(credit__gt=0)
        assert credit_line.account.code == '1200'  # Advances to PMs
        assert credit_line.credit == Decimal('5000.00')
        assert credit_line.partner == employee


class TestRule3CashReturnedByPM:
    """Test Rule 3: Cash returned by PM."""

    def test_advance_return_creates_correct_journal_entry(
        self, accounts, journals, employee, project
    ):
        """
        Cash returned by PM:
        - Debit: Cash
        - Credit: Advances to PMs (partner=PM)
        """
        # First create and post an advance
        advance = CashAdvance.objects.create(
            project=project,
            recipient=employee,
            date=date.today(),
            purpose='شراء مواد بناء',
            amount=Decimal('10000.00'),
            amount_base=Decimal('10000.00'),
        )
        advance.post()

        # Create return
        return_obj = AdvanceReturn.objects.create(
            advance=advance,
            date=date.today(),
            amount=Decimal('3000.00'),
            amount_base=Decimal('3000.00'),
            notes='إرجاع المبلغ المتبقي',
        )
        return_obj.post()

        # Verify entry was created
        assert return_obj.journal_entry is not None
        assert return_obj.status == 'posted'

        # Check journal entry lines
        lines = return_obj.journal_entry.lines.all()
        assert lines.count() == 2

        # Check debit to cash account
        debit_line = lines.get(debit__gt=0)
        assert debit_line.account.code == '1000'  # Cash
        assert debit_line.debit == Decimal('3000.00')

        # Check credit to advances account
        credit_line = lines.get(credit__gt=0)
        assert credit_line.account.code == '1200'  # Advances to PMs
        assert credit_line.credit == Decimal('3000.00')
        assert credit_line.partner == employee


class TestRule4CustomerInvoice:
    """Test Rule 4: Customer invoice."""

    def test_invoice_creates_correct_journal_entry(
        self, accounts, journals, customer, project
    ):
        """
        Customer invoice:
        - Debit: Accounts Receivable (partner, project)
        - Credit: Project Revenue (project)
        """
        invoice = Invoice.objects.create(
            project=project,
            customer=customer,
            date=date.today(),
            due_date=date.today() + timedelta(days=30),
            description='دفعة أولى للمشروع',
            amount=Decimal('50000.00'),
            amount_base=Decimal('50000.00'),
        )
        invoice.post()

        # Verify entry was created
        assert invoice.journal_entry is not None
        assert invoice.status == 'posted'

        # Check journal entry lines
        lines = invoice.journal_entry.lines.all()
        assert lines.count() == 2

        # Check debit to AR account
        debit_line = lines.get(debit__gt=0)
        assert debit_line.account.code == '1100'  # AR
        assert debit_line.debit == Decimal('50000.00')
        assert debit_line.partner == customer
        assert debit_line.project == project

        # Check credit to revenue account
        credit_line = lines.get(credit__gt=0)
        assert credit_line.account.code == '4000'  # Revenue
        assert credit_line.credit == Decimal('50000.00')
        assert credit_line.project == project


class TestRule5SupplierBill:
    """Test Rule 5: Supplier bill."""

    def test_bill_creates_correct_journal_entry(
        self, accounts, journals, supplier, project
    ):
        """
        Supplier bill:
        - Debit: Expense account (project or none)
        - Credit: Accounts Payable (partner, project)
        """
        bill = Bill.objects.create(
            project=project,
            supplier=supplier,
            account=accounts['expense'],
            date=date.today(),
            due_date=date.today() + timedelta(days=30),
            description='توريد مواد بناء',
            amount=Decimal('25000.00'),
            amount_base=Decimal('25000.00'),
        )
        bill.post()

        # Verify entry was created
        assert bill.journal_entry is not None
        assert bill.status == 'posted'

        # Check journal entry lines
        lines = bill.journal_entry.lines.all()
        assert lines.count() == 2

        # Check debit to expense account
        debit_line = lines.get(debit__gt=0)
        assert debit_line.account.code == '5000'  # Expense
        assert debit_line.debit == Decimal('25000.00')
        assert debit_line.project == project

        # Check credit to AP account
        credit_line = lines.get(credit__gt=0)
        assert credit_line.account.code == '2000'  # AP
        assert credit_line.credit == Decimal('25000.00')
        assert credit_line.partner == supplier


class TestRule6PaymentReceived:
    """Test Rule 6: Payment received from customer."""

    def test_inbound_payment_creates_correct_journal_entry(
        self, accounts, journals, customer
    ):
        """
        Payment received:
        - Debit: Cash/Bank
        - Credit: Accounts Receivable (partner)
        """
        payment = Payment.objects.create(
            direction='inbound',
            partner=customer,
            date=date.today(),
            account=accounts['cash'],
            amount=Decimal('30000.00'),
            amount_base=Decimal('30000.00'),
            reference='CHK-12345',
        )
        payment.post()

        # Verify entry was created
        assert payment.journal_entry is not None
        assert payment.status == 'posted'

        # Check journal entry lines
        lines = payment.journal_entry.lines.all()
        assert lines.count() == 2

        # Check debit to cash account
        debit_line = lines.get(debit__gt=0)
        assert debit_line.account.code == '1000'  # Cash
        assert debit_line.debit == Decimal('30000.00')

        # Check credit to AR account
        credit_line = lines.get(credit__gt=0)
        assert credit_line.account.code == '1100'  # AR
        assert credit_line.credit == Decimal('30000.00')
        assert credit_line.partner == customer


class TestRule7PaymentMade:
    """Test Rule 7: Payment made to supplier."""

    def test_outbound_payment_creates_correct_journal_entry(
        self, accounts, journals, supplier
    ):
        """
        Payment made:
        - Debit: Accounts Payable (partner)
        - Credit: Cash/Bank
        """
        payment = Payment.objects.create(
            direction='outbound',
            partner=supplier,
            date=date.today(),
            account=accounts['cash'],
            amount=Decimal('20000.00'),
            amount_base=Decimal('20000.00'),
            reference='TRN-54321',
        )
        payment.post()

        # Verify entry was created
        assert payment.journal_entry is not None
        assert payment.status == 'posted'

        # Check journal entry lines
        lines = payment.journal_entry.lines.all()
        assert lines.count() == 2

        # Check debit to AP account
        debit_line = lines.get(debit__gt=0)
        assert debit_line.account.code == '2000'  # AP
        assert debit_line.debit == Decimal('20000.00')
        assert debit_line.partner == supplier

        # Check credit to cash account
        credit_line = lines.get(credit__gt=0)
        assert credit_line.account.code == '1000'  # Cash
        assert credit_line.credit == Decimal('20000.00')


class TestRule8DirectExpense:
    """Test Rule 8: Direct company/project expense."""

    def test_direct_expense_creates_correct_journal_entry(
        self, accounts, journals, project
    ):
        """
        Direct expense (without advance):
        - Debit: Expense account (project or none)
        - Credit: Cash/Bank
        """
        expense = Expense.objects.create(
            date=date.today(),
            project=project,
            advance=None,  # Direct expense, no advance
            account=accounts['expense'],
            description='مصروفات نثرية',
            amount=Decimal('1500.00'),
            amount_base=Decimal('1500.00'),
        )
        expense.post()

        # Verify entry was created
        assert expense.journal_entry is not None
        assert expense.status == 'posted'

        # Check journal entry lines
        lines = expense.journal_entry.lines.all()
        assert lines.count() == 2

        # Check debit to expense account
        debit_line = lines.get(debit__gt=0)
        assert debit_line.account.code == '5000'  # Expense
        assert debit_line.debit == Decimal('1500.00')
        assert debit_line.project == project

        # Check credit to cash account
        credit_line = lines.get(credit__gt=0)
        assert credit_line.account.code == '1000'  # Cash
        assert credit_line.credit == Decimal('1500.00')

    def test_company_expense_no_project(self, accounts, journals):
        """Test direct company expense without project."""
        expense = Expense.objects.create(
            date=date.today(),
            project=None,  # Company-level expense
            advance=None,
            account=accounts['expense'],
            description='مصروفات إدارية عامة',
            amount=Decimal('2000.00'),
            amount_base=Decimal('2000.00'),
        )
        expense.post()

        # Verify entry was created
        assert expense.journal_entry is not None
        assert expense.status == 'posted'

        # Check that project is null on lines
        lines = expense.journal_entry.lines.all()
        debit_line = lines.get(debit__gt=0)
        assert debit_line.project is None
