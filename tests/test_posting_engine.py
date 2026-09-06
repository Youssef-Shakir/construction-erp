"""
Tests for the accounting posting engine.

Tests:
- Debits must equal credits
- Atomic transactions (all or nothing)
- Immutability of posted entries
- Entry reversal
"""
import pytest
from decimal import Decimal
from datetime import date
from django.db import transaction as db_transaction
from django.core.exceptions import ValidationError

from apps.accounting.models import AccountType, Account, Journal, JournalEntry, JournalLine
from apps.accounting.posting import (
    create_journal_entry, post_entry, reverse_entry,
    get_account_balance, get_trial_balance, PostingError
)


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
    accounts = {
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
    return accounts


@pytest.fixture
def journal(db):
    """Create a journal."""
    return Journal.objects.create(
        code='GEN', name='القيود العامة', type='general'
    )


@pytest.fixture
def cash_journal(db):
    """Create a cash journal."""
    return Journal.objects.create(
        code='CASH', name='يومية النقدية', type='cash'
    )


class TestDebitsCreditEquality:
    """Test that debits must equal credits."""

    def test_balanced_entry_succeeds(self, accounts, journal):
        """Test that a balanced entry is created successfully."""
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('1000.00')},
            {'account': accounts['revenue'], 'credit': Decimal('1000.00')},
        ]
        entry = create_journal_entry(
            journal=journal,
            date=date.today(),
            lines=lines,
            memo='Test entry'
        )

        assert entry is not None
        assert entry.is_posted
        assert entry.total_debit == Decimal('1000.00')
        assert entry.total_credit == Decimal('1000.00')
        assert entry.is_balanced

    def test_unbalanced_entry_fails(self, accounts, journal):
        """Test that an unbalanced entry raises PostingError."""
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('1000.00')},
            {'account': accounts['revenue'], 'credit': Decimal('500.00')},
        ]

        with pytest.raises(PostingError) as exc_info:
            create_journal_entry(
                journal=journal,
                date=date.today(),
                lines=lines,
                memo='Unbalanced entry'
            )

        assert 'غير متوازن' in str(exc_info.value)

    def test_zero_total_fails(self, accounts, journal):
        """Test that an entry with zero total fails."""
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('0.00')},
            {'account': accounts['revenue'], 'credit': Decimal('0.00')},
        ]

        with pytest.raises(PostingError) as exc_info:
            create_journal_entry(
                journal=journal,
                date=date.today(),
                lines=lines,
                memo='Zero entry'
            )

        assert 'صفراً' in str(exc_info.value) or 'سطرين' in str(exc_info.value)

    def test_single_line_fails(self, accounts, journal):
        """Test that a single-line entry fails."""
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('1000.00')},
        ]

        with pytest.raises(PostingError) as exc_info:
            create_journal_entry(
                journal=journal,
                date=date.today(),
                lines=lines,
                memo='Single line entry'
            )

        assert 'سطرين' in str(exc_info.value)


class TestAtomicity:
    """Test that posting is atomic (all or nothing)."""

    def test_entry_creation_is_atomic(self, accounts, journal):
        """Test that entry creation is atomic."""
        # Create a valid entry first to know the next number
        initial_count = JournalEntry.objects.count()

        # Try to create an invalid entry
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('1000.00')},
            {'account': accounts['revenue'], 'credit': Decimal('999.00')},  # Unbalanced
        ]

        with pytest.raises(PostingError):
            create_journal_entry(
                journal=journal,
                date=date.today(),
                lines=lines,
                memo='Should fail'
            )

        # No entry should have been created
        assert JournalEntry.objects.count() == initial_count

    def test_successful_entry_creates_all_lines(self, accounts, journal):
        """Test that a successful entry creates all lines."""
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('1000.00')},
            {'account': accounts['expense'], 'debit': Decimal('500.00')},
            {'account': accounts['revenue'], 'credit': Decimal('1500.00')},
        ]

        entry = create_journal_entry(
            journal=journal,
            date=date.today(),
            lines=lines,
            memo='Multi-line entry'
        )

        assert entry.lines.count() == 3


class TestImmutability:
    """Test that posted entries are immutable."""

    def test_posted_entry_cannot_be_modified(self, accounts, journal):
        """Test that a posted entry cannot be modified."""
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('1000.00')},
            {'account': accounts['revenue'], 'credit': Decimal('1000.00')},
        ]
        entry = create_journal_entry(
            journal=journal,
            date=date.today(),
            lines=lines,
            memo='Test entry',
            auto_post=True
        )

        assert entry.is_posted

        # Try to modify the entry
        entry.memo = 'Modified memo'
        with pytest.raises(ValidationError):
            entry.clean()

    def test_cannot_post_already_posted_entry(self, accounts, journal):
        """Test that posting an already-posted entry fails."""
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('1000.00')},
            {'account': accounts['revenue'], 'credit': Decimal('1000.00')},
        ]
        entry = create_journal_entry(
            journal=journal,
            date=date.today(),
            lines=lines,
            memo='Test entry',
            auto_post=True
        )

        with pytest.raises(PostingError) as exc_info:
            post_entry(entry)

        assert 'مرحّل بالفعل' in str(exc_info.value)


class TestReversal:
    """Test entry reversal functionality."""

    def test_can_reverse_posted_entry(self, accounts, journal):
        """Test that a posted entry can be reversed."""
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('1000.00')},
            {'account': accounts['revenue'], 'credit': Decimal('1000.00')},
        ]
        entry = create_journal_entry(
            journal=journal,
            date=date.today(),
            lines=lines,
            memo='Original entry',
            auto_post=True
        )

        reversal = reverse_entry(entry, date.today(), memo='Reversal')

        # Check reversal entry
        assert reversal.is_posted
        assert reversal.reverses == entry

        # Check original entry is marked as reversed
        entry.refresh_from_db()
        assert entry.is_reversed
        assert entry.reversed_by == reversal

        # Check amounts are swapped
        original_lines = {line.account.code: line for line in entry.lines.all()}
        reversal_lines = {line.account.code: line for line in reversal.lines.all()}

        assert reversal_lines['1000'].credit == original_lines['1000'].debit
        assert reversal_lines['4000'].debit == original_lines['4000'].credit

    def test_cannot_reverse_unposted_entry(self, accounts, journal):
        """Test that an unposted entry cannot be reversed."""
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('1000.00')},
            {'account': accounts['revenue'], 'credit': Decimal('1000.00')},
        ]
        entry = create_journal_entry(
            journal=journal,
            date=date.today(),
            lines=lines,
            memo='Draft entry',
            auto_post=False
        )

        with pytest.raises(PostingError) as exc_info:
            reverse_entry(entry, date.today())

        assert 'غير مرحّل' in str(exc_info.value)

    def test_cannot_reverse_already_reversed_entry(self, accounts, journal):
        """Test that an already-reversed entry cannot be reversed again."""
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('1000.00')},
            {'account': accounts['revenue'], 'credit': Decimal('1000.00')},
        ]
        entry = create_journal_entry(
            journal=journal,
            date=date.today(),
            lines=lines,
            memo='Original entry',
            auto_post=True
        )

        reverse_entry(entry, date.today())

        with pytest.raises(PostingError) as exc_info:
            reverse_entry(entry, date.today())

        assert 'ملغي بالفعل' in str(exc_info.value)

    def test_reversal_zeroes_out_balances(self, accounts, journal):
        """Test that reversing an entry zeroes out the account balances."""
        # Check initial balance
        initial_balance = accounts['cash'].balance

        # Create and post entry
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('1000.00')},
            {'account': accounts['revenue'], 'credit': Decimal('1000.00')},
        ]
        entry = create_journal_entry(
            journal=journal,
            date=date.today(),
            lines=lines,
            memo='Test entry',
            auto_post=True
        )

        # Check balance increased
        assert accounts['cash'].balance == initial_balance + Decimal('1000.00')

        # Reverse entry
        reverse_entry(entry, date.today())

        # Check balance is back to initial
        assert accounts['cash'].balance == initial_balance


class TestAccountBalances:
    """Test account balance calculations."""

    def test_debit_account_balance(self, accounts, journal):
        """Test balance calculation for debit-normal accounts."""
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('5000.00')},
            {'account': accounts['revenue'], 'credit': Decimal('5000.00')},
        ]
        create_journal_entry(
            journal=journal,
            date=date.today(),
            lines=lines,
            memo='Revenue entry',
            auto_post=True
        )

        assert accounts['cash'].balance == Decimal('5000.00')

    def test_credit_account_balance(self, accounts, journal):
        """Test balance calculation for credit-normal accounts."""
        lines = [
            {'account': accounts['cash'], 'debit': Decimal('3000.00')},
            {'account': accounts['revenue'], 'credit': Decimal('3000.00')},
        ]
        create_journal_entry(
            journal=journal,
            date=date.today(),
            lines=lines,
            memo='Revenue entry',
            auto_post=True
        )

        assert accounts['revenue'].balance == Decimal('3000.00')

    def test_draft_entries_not_in_balance(self, accounts, journal):
        """Test that draft entries don't affect balance."""
        initial_balance = accounts['cash'].balance

        lines = [
            {'account': accounts['cash'], 'debit': Decimal('1000.00')},
            {'account': accounts['revenue'], 'credit': Decimal('1000.00')},
        ]
        create_journal_entry(
            journal=journal,
            date=date.today(),
            lines=lines,
            memo='Draft entry',
            auto_post=False
        )

        # Balance should not change
        assert accounts['cash'].balance == initial_balance


class TestTrialBalance:
    """Test trial balance generation."""

    def test_trial_balance_is_balanced(self, accounts, journal):
        """Test that trial balance always balances."""
        # Create several entries
        lines1 = [
            {'account': accounts['cash'], 'debit': Decimal('10000.00')},
            {'account': accounts['revenue'], 'credit': Decimal('10000.00')},
        ]
        create_journal_entry(journal=journal, date=date.today(), lines=lines1, auto_post=True)

        lines2 = [
            {'account': accounts['expense'], 'debit': Decimal('3000.00')},
            {'account': accounts['cash'], 'credit': Decimal('3000.00')},
        ]
        create_journal_entry(journal=journal, date=date.today(), lines=lines2, auto_post=True)

        # Get trial balance
        tb = get_trial_balance()

        assert tb['is_balanced']
        assert tb['total_debit'] == tb['total_credit']
