"""
Regression tests for the production-hardening review.

Each test pins down a bug that existed before the review:
- posted journal entries / lines could be edited or deleted through the ORM
- reports used abs() so contra balances (overdraft, refunds) had the wrong sign
- ledger opening balance double-counted the first day
- inactive accounts disappeared from the trial balance
- advance-linked expenses / returns were not re-checked against the advance at post time
- payments could be allocated to another partner's invoice, or to the wrong document type
- document numbers came from last.id + 1 (collisions under concurrency)
- reversing a document's entry from the journal screen left the document 'posted'
"""
import os
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounting.models import Account, JournalEntry
from apps.accounting.posting import (
    PostingError, create_journal_entry, get_account_balance, get_balance_sheet,
    get_income_statement, get_trial_balance, reverse_entry,
)
from apps.advances.models import AdvanceReturn, CashAdvance
from apps.core.models import Partner
from apps.core.sequences import next_document_number
from apps.expenses.models import Expense
from apps.invoicing.models import Bill, Invoice
from apps.payments.models import Payment
from apps.payments.services import allocate_payment

# Shared fixtures
from tests.test_journal_rules import (  # noqa: F401
    account_types, accounts, journals, customer, supplier, employee, project,
)

D = Decimal


def _entry(journals, accounts, debit_acc, credit_acc, amount, on=date(2026, 1, 10)):
    return create_journal_entry(
        journal=journals['general'], date=on,
        lines=[
            {'account': accounts[debit_acc], 'debit': D(amount)},
            {'account': accounts[credit_acc], 'credit': D(amount)},
        ],
    )


# --------------------------------------------------------------------------
# Ledger immutability
# --------------------------------------------------------------------------
class TestImmutability:
    def test_posted_entry_save_is_blocked(self, accounts, journals):
        entry = _entry(journals, accounts, 'cash', 'revenue', '100')
        entry.memo = 'tampered'
        with pytest.raises(ValidationError):
            entry.save()

    def test_posted_entry_delete_is_blocked(self, accounts, journals):
        entry = _entry(journals, accounts, 'cash', 'revenue', '100')
        with pytest.raises(ValidationError):
            entry.delete()

    def test_posted_line_cannot_be_edited_or_deleted(self, accounts, journals):
        entry = _entry(journals, accounts, 'cash', 'revenue', '100')
        line = entry.lines.first()
        line.debit = D('999')
        with pytest.raises(ValidationError):
            line.save()
        with pytest.raises(ValidationError):
            line.delete()

    def test_reversal_bookkeeping_still_allowed(self, accounts, journals):
        entry = _entry(journals, accounts, 'cash', 'revenue', '100')
        reversal = reverse_entry(entry, date(2026, 1, 11))
        entry.refresh_from_db()
        assert entry.is_reversed and entry.reversed_by == reversal
        assert reversal.reverses == entry

    def test_inactive_account_rejected_but_reversal_allowed(self, accounts, journals):
        entry = _entry(journals, accounts, 'cash', 'revenue', '100')
        Account.objects.filter(pk=accounts['revenue'].pk).update(is_active=False)
        accounts['revenue'].refresh_from_db()
        with pytest.raises(PostingError):
            _entry(journals, accounts, 'cash', 'revenue', '50')
        reverse_entry(entry, date(2026, 1, 11))  # must not raise


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
class TestReports:
    def test_overdraft_reduces_assets(self, accounts, journals):
        # Bank overdraft: credit bank 300 against an expense
        _entry(journals, accounts, 'expense', 'bank', '300')
        bs = get_balance_sheet(date(2026, 12, 31))
        bank_row = next(r for r in bs['asset_data'] if r['account'] == accounts['bank'])
        assert bank_row['balance'] == D('-300')
        assert bs['total_assets'] == D('-300')
        assert bs['is_balanced']

    def test_revenue_refund_reduces_revenue(self, accounts, journals):
        _entry(journals, accounts, 'cash', 'revenue', '1000')
        _entry(journals, accounts, 'revenue', 'cash', '200')   # refund
        _entry(journals, accounts, 'revenue', 'bank', '1000')  # more refunds than sales
        stmt = get_income_statement(date(2026, 12, 31))
        assert stmt['total_revenue'] == D('-200')

    def test_balance_sheet_balances_with_earnings(self, accounts, journals):
        _entry(journals, accounts, 'cash', 'revenue', '1000')
        _entry(journals, accounts, 'expense', 'cash', '400')
        bs = get_balance_sheet(date(2026, 12, 31))
        assert bs['retained_earnings'] == D('600')
        assert bs['total_assets'] == bs['total_liabilities_and_equity'] == D('600')

    def test_inactive_account_stays_in_trial_balance(self, accounts, journals):
        _entry(journals, accounts, 'cash', 'revenue', '100')
        Account.objects.filter(pk=accounts['revenue'].pk).update(is_active=False)
        tb = get_trial_balance()
        assert tb['is_balanced']
        assert tb['total_debit'] == D('100')

    def test_opening_balance_excludes_the_start_day(self, accounts, journals):
        _entry(journals, accounts, 'cash', 'revenue', '100', on=date(2026, 1, 9))
        _entry(journals, accounts, 'cash', 'revenue', '50', on=date(2026, 1, 10))
        cash = accounts['cash']
        assert get_account_balance(cash, before_date=date(2026, 1, 10)) == D('100')
        assert get_account_balance(cash, as_of_date=date(2026, 1, 10)) == D('150')


# --------------------------------------------------------------------------
# Advance over-spend protection at posting time
# --------------------------------------------------------------------------
@pytest.fixture
def advance(accounts, journals, employee, project):
    adv = CashAdvance.objects.create(
        project=project, recipient=employee, date=date(2026, 1, 1),
        purpose='Site materials', amount=D('1000'),
    )
    adv.post()
    return adv


class TestAdvanceOverspend:
    def _expense(self, advance, accounts, amount):
        return Expense.objects.create(
            date=date(2026, 1, 2), advance=advance, project=advance.project,
            account=accounts['expense'], description='x', amount=D(amount),
        )

    def test_two_drafts_cannot_overspend(self, advance, accounts):
        e1 = self._expense(advance, accounts, '700')
        e2 = self._expense(advance, accounts, '700')  # each fits alone
        e1.post()
        with pytest.raises(PostingError):
            e2.post()
        assert advance.remaining == D('300')

    def test_return_rechecked_at_post(self, advance, accounts):
        r1 = AdvanceReturn.objects.create(advance=advance, date=date(2026, 1, 3), amount=D('800'))
        r2 = AdvanceReturn.objects.create(advance=advance, date=date(2026, 1, 3), amount=D('800'))
        r1.post()
        with pytest.raises(PostingError):
            r2.post()

    def test_return_can_be_cancelled(self, advance):
        ret = AdvanceReturn.objects.create(advance=advance, date=date(2026, 1, 3), amount=D('400'))
        ret.post()
        assert advance.remaining == D('600')
        ret.cancel()
        assert ret.status == 'cancelled'
        assert advance.remaining == D('1000')
        assert ret.journal_entry.is_reversed

    def test_double_post_is_rejected(self, advance, accounts):
        e = self._expense(advance, accounts, '100')
        stale = Expense.objects.get(pk=e.pk)  # second "request" loaded before first posted
        e.post()
        with pytest.raises(PostingError):
            stale.post()
        assert JournalEntry.objects.filter(reference=e.expense_number).count() == 1


# --------------------------------------------------------------------------
# Payment allocation
# --------------------------------------------------------------------------
@pytest.fixture
def posted_invoice(accounts, journals, customer, project):
    inv = Invoice.objects.create(
        project=project, customer=customer, date=date(2026, 1, 1),
        due_date=date(2026, 2, 1), description='Progress bill 1', amount=D('1000'),
    )
    inv.post()
    return inv


def _payment(partner, accounts, direction, amount='500'):
    p = Payment.objects.create(
        direction=direction, partner=partner, date=date(2026, 1, 5),
        account=accounts['cash'], amount=D(amount),
    )
    p.post()
    return p


class TestAllocation:
    def test_happy_path(self, posted_invoice, customer, accounts):
        pay = _payment(customer, accounts, 'inbound')
        allocate_payment(pay, posted_invoice, D('500'))
        assert posted_invoice.amount_remaining == D('500')

    def test_rejects_other_customers_invoice(self, posted_invoice, accounts):
        other = Partner.objects.create(code='CUST002', name='Other', type='customer')
        pay = _payment(other, accounts, 'inbound')
        with pytest.raises(PostingError):
            allocate_payment(pay, posted_invoice, D('100'))

    def test_rejects_wrong_document_type(self, accounts, journals, supplier, customer, project):
        bill = Bill.objects.create(
            supplier=supplier, project=project, account=accounts['expense'],
            date=date(2026, 1, 1), due_date=date(2026, 2, 1), description='Cement', amount=D('300'),
        )
        bill.post()
        pay = _payment(customer, accounts, 'inbound')
        with pytest.raises(PostingError):
            allocate_payment(pay, bill, D('100'))

    def test_rejects_draft_invoice_and_over_allocation(self, posted_invoice, customer, accounts, project):
        draft = Invoice.objects.create(
            project=project, customer=customer, date=date(2026, 1, 1),
            due_date=date(2026, 2, 1), description='draft', amount=D('100'),
        )
        pay = _payment(customer, accounts, 'inbound', amount='2000')
        with pytest.raises(PostingError):
            allocate_payment(pay, draft, D('50'))
        with pytest.raises(PostingError):
            allocate_payment(pay, posted_invoice, D('1500'))  # > invoice remaining


# --------------------------------------------------------------------------
# Numbering + reversal of document-owned entries
# --------------------------------------------------------------------------
class TestNumberingAndReversal:
    def test_sequence_continues_after_existing_numbers(self, posted_invoice):
        # posted_invoice already took INV-000001 via the sequence
        assert posted_invoice.invoice_number == 'INV-000001'
        assert next_document_number('INV', Invoice, 'invoice_number') == 'INV-000002'

    def test_sequence_seeds_from_legacy_numbers(self, customer, project, accounts, journals):
        Invoice.objects.create(
            invoice_number='LEG-000041', project=project, customer=customer,
            date=date(2026, 1, 1), due_date=date(2026, 1, 1), description='legacy', amount=D('1'),
        )
        assert next_document_number('LEG', Invoice, 'invoice_number') == 'LEG-000042'

    def test_document_entry_cannot_be_reversed_from_journal(self, client, posted_invoice, django_user_model):
        admin = django_user_model.objects.create_superuser(
            email='admin@example.com', password='x', first_name='A', last_name='B',
        )
        client.force_login(admin)
        url = reverse('accounting:entry_reverse', args=[posted_invoice.journal_entry_id])
        client.post(url)
        posted_invoice.journal_entry.refresh_from_db()
        assert not posted_invoice.journal_entry.is_reversed


@pytest.mark.django_db
def test_seed_demo_sets_normal_balances():
    """seed_demo used to leave normal_balance blank, flipping asset/expense signs."""
    from django.core.management import call_command
    from apps.accounting.models import AccountType
    call_command('seed_demo', stdout=open(os.devnull, 'w'))
    normal = dict(AccountType.objects.values_list('code', 'normal_balance'))
    assert normal['asset'] == 'debit' and normal['expense'] == 'debit'
    assert normal['liability'] == normal['equity'] == normal['revenue'] == 'credit'
