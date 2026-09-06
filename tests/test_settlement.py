"""
Tests for advance settlement calculations.

Settlement figures (all derived):
- original advance
- total expenses posted
- cash returned
- remaining = advance - expenses - returned
- unaccounted = remaining once advance is closed
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from apps.accounting.models import AccountType, Account, Journal
from apps.core.models import Partner
from apps.projects.models import Project
from apps.advances.models import CashAdvance, AdvanceReturn
from apps.expenses.models import Expense
from apps.accounting.posting import PostingError


@pytest.fixture
def account_types(db):
    """Create standard account types."""
    types = [
        ('asset', 'الأصول', 'debit', 'balance_sheet', 1),
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
        'advances': Account.objects.create(
            code='1200', name='سلف الموظفين', account_type=account_types['asset'], is_control=True
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
    }


@pytest.fixture
def employee(db):
    """Create an employee partner."""
    return Partner.objects.create(
        code='EMP001',
        name='أحمد محمد',
        type='employee'
    )


@pytest.fixture
def customer(db):
    """Create a customer partner."""
    return Partner.objects.create(
        code='CUST001',
        name='شركة البناء',
        type='customer'
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


@pytest.fixture
def posted_advance(db, accounts, journals, employee, project):
    """Create a posted advance."""
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


class TestSettlementCalculations:
    """Test settlement math calculations."""

    def test_initial_settlement_figures(self, posted_advance):
        """Test initial settlement figures for a new advance."""
        assert posted_advance.amount == Decimal('10000.00')
        assert posted_advance.total_expenses == Decimal('0.00')
        assert posted_advance.total_returned == Decimal('0.00')
        assert posted_advance.total_settled == Decimal('0.00')
        assert posted_advance.remaining == Decimal('10000.00')
        assert not posted_advance.is_fully_settled

    def test_settlement_with_expenses(self, posted_advance, accounts):
        """Test settlement with expenses."""
        # Create and post expense
        expense = Expense.objects.create(
            date=date.today(),
            project=posted_advance.project,
            advance=posted_advance,
            account=accounts['expense'],
            description='شراء حديد',
            amount=Decimal('4000.00'),
            amount_base=Decimal('4000.00'),
        )
        expense.post()

        # Check settlement figures
        assert posted_advance.total_expenses == Decimal('4000.00')
        assert posted_advance.total_returned == Decimal('0.00')
        assert posted_advance.total_settled == Decimal('4000.00')
        assert posted_advance.remaining == Decimal('6000.00')
        assert not posted_advance.is_fully_settled

    def test_settlement_with_return(self, posted_advance):
        """Test settlement with cash return."""
        # Create and post return
        return_obj = AdvanceReturn.objects.create(
            advance=posted_advance,
            date=date.today(),
            amount=Decimal('3000.00'),
            amount_base=Decimal('3000.00'),
        )
        return_obj.post()

        # Check settlement figures
        assert posted_advance.total_expenses == Decimal('0.00')
        assert posted_advance.total_returned == Decimal('3000.00')
        assert posted_advance.total_settled == Decimal('3000.00')
        assert posted_advance.remaining == Decimal('7000.00')
        assert not posted_advance.is_fully_settled

    def test_settlement_with_expenses_and_return(self, posted_advance, accounts):
        """Test settlement with both expenses and return."""
        # Create and post expense
        expense = Expense.objects.create(
            date=date.today(),
            project=posted_advance.project,
            advance=posted_advance,
            account=accounts['expense'],
            description='شراء حديد',
            amount=Decimal('6000.00'),
            amount_base=Decimal('6000.00'),
        )
        expense.post()

        # Create and post return
        return_obj = AdvanceReturn.objects.create(
            advance=posted_advance,
            date=date.today(),
            amount=Decimal('2000.00'),
            amount_base=Decimal('2000.00'),
        )
        return_obj.post()

        # Check settlement figures
        assert posted_advance.total_expenses == Decimal('6000.00')
        assert posted_advance.total_returned == Decimal('2000.00')
        assert posted_advance.total_settled == Decimal('8000.00')
        assert posted_advance.remaining == Decimal('2000.00')
        assert not posted_advance.is_fully_settled

    def test_full_settlement_with_expenses(self, posted_advance, accounts):
        """Test full settlement using only expenses."""
        # Create and post expense for full amount
        expense = Expense.objects.create(
            date=date.today(),
            project=posted_advance.project,
            advance=posted_advance,
            account=accounts['expense'],
            description='شراء مواد بناء كاملة',
            amount=Decimal('10000.00'),
            amount_base=Decimal('10000.00'),
        )
        expense.post()

        # Check settlement figures
        assert posted_advance.total_expenses == Decimal('10000.00')
        assert posted_advance.total_returned == Decimal('0.00')
        assert posted_advance.remaining == Decimal('0.00')
        assert posted_advance.is_fully_settled

    def test_full_settlement_with_mixed(self, posted_advance, accounts):
        """Test full settlement using expenses and return."""
        # Create and post expense
        expense = Expense.objects.create(
            date=date.today(),
            project=posted_advance.project,
            advance=posted_advance,
            account=accounts['expense'],
            description='شراء مواد',
            amount=Decimal('7500.00'),
            amount_base=Decimal('7500.00'),
        )
        expense.post()

        # Create and post return for remaining
        return_obj = AdvanceReturn.objects.create(
            advance=posted_advance,
            date=date.today(),
            amount=Decimal('2500.00'),
            amount_base=Decimal('2500.00'),
        )
        return_obj.post()

        # Check settlement figures
        assert posted_advance.remaining == Decimal('0.00')
        assert posted_advance.is_fully_settled

    def test_multiple_expenses(self, posted_advance, accounts):
        """Test settlement with multiple expenses."""
        # Create multiple expenses
        for i, amount in enumerate([3000, 2000, 1500]):
            expense = Expense.objects.create(
                date=date.today(),
                project=posted_advance.project,
                advance=posted_advance,
                account=accounts['expense'],
                description=f'مصروف {i+1}',
                amount=Decimal(str(amount)),
                amount_base=Decimal(str(amount)),
            )
            expense.post()

        # Check settlement figures
        assert posted_advance.total_expenses == Decimal('6500.00')
        assert posted_advance.remaining == Decimal('3500.00')

    def test_draft_expenses_not_counted(self, posted_advance, accounts):
        """Test that draft expenses don't affect settlement."""
        # Create a draft expense
        expense = Expense.objects.create(
            date=date.today(),
            project=posted_advance.project,
            advance=posted_advance,
            account=accounts['expense'],
            description='مصروف مسودة',
            amount=Decimal('5000.00'),
            amount_base=Decimal('5000.00'),
            status='draft',
        )

        # Check that draft doesn't affect settlement
        assert posted_advance.total_expenses == Decimal('0.00')
        assert posted_advance.remaining == Decimal('10000.00')


class TestSettlementValidation:
    """Test validation rules for settlement."""

    def test_cannot_exceed_advance_amount(self, posted_advance, accounts):
        """Test that expenses cannot exceed advance amount."""
        # Try to create expense exceeding advance
        expense = Expense(
            date=date.today(),
            project=posted_advance.project,
            advance=posted_advance,
            account=accounts['expense'],
            description='مصروف كبير',
            amount=Decimal('15000.00'),  # More than advance
            amount_base=Decimal('15000.00'),
        )

        with pytest.raises(Exception):  # ValidationError
            expense.clean()

    def test_return_cannot_exceed_remaining(self, posted_advance, accounts):
        """Test that return cannot exceed remaining amount."""
        # First post some expenses
        expense = Expense.objects.create(
            date=date.today(),
            project=posted_advance.project,
            advance=posted_advance,
            account=accounts['expense'],
            description='مصروف',
            amount=Decimal('7000.00'),
            amount_base=Decimal('7000.00'),
        )
        expense.post()

        # Try to return more than remaining
        return_obj = AdvanceReturn(
            advance=posted_advance,
            date=date.today(),
            amount=Decimal('5000.00'),  # More than remaining 3000
            amount_base=Decimal('5000.00'),
        )

        with pytest.raises(Exception):  # ValidationError
            return_obj.clean()


class TestAdvanceLifecycle:
    """Test advance lifecycle operations."""

    def test_close_fully_settled_advance(self, posted_advance, accounts):
        """Test closing a fully settled advance."""
        # Settle the advance fully
        expense = Expense.objects.create(
            date=date.today(),
            project=posted_advance.project,
            advance=posted_advance,
            account=accounts['expense'],
            description='مصروف كامل',
            amount=Decimal('10000.00'),
            amount_base=Decimal('10000.00'),
        )
        expense.post()

        # Close the advance
        posted_advance.close()

        assert posted_advance.status == 'closed'

    def test_cannot_close_unsettled_advance(self, posted_advance):
        """Test that unsettled advance cannot be closed."""
        with pytest.raises(PostingError) as exc_info:
            posted_advance.close()

        assert 'غير مسوّاة' in str(exc_info.value)

    def test_cancel_advance_without_activity(self, posted_advance):
        """Test cancelling advance with no expenses or returns."""
        posted_advance.cancel()

        assert posted_advance.status == 'cancelled'
        assert posted_advance.journal_entry.is_reversed

    def test_cannot_cancel_advance_with_expenses(self, posted_advance, accounts):
        """Test that advance with expenses cannot be cancelled."""
        # Post an expense
        expense = Expense.objects.create(
            date=date.today(),
            project=posted_advance.project,
            advance=posted_advance,
            account=accounts['expense'],
            description='مصروف',
            amount=Decimal('3000.00'),
            amount_base=Decimal('3000.00'),
        )
        expense.post()

        with pytest.raises(PostingError) as exc_info:
            posted_advance.cancel()

        assert 'مصروفات' in str(exc_info.value)
