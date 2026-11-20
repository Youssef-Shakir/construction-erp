"""
Tests for invoice and bill payment status calculations.

Tests for:
- amount_paid calculation from PaymentAllocation
- amount_remaining calculation
- is_paid status
- is_overdue status
- payment_status display
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from django.contrib.contenttypes.models import ContentType

from apps.accounting.models import AccountType, Account, Journal
from apps.core.models import Partner
from apps.projects.models import Project
from apps.invoicing.models import Invoice, Bill
from apps.payments.models import Payment, PaymentAllocation


@pytest.fixture
def account_types(db):
    """Create standard account types."""
    types = [
        ('asset', 'الأصول', 'debit', 'balance_sheet', 1),
        ('liability', 'الخصوم', 'credit', 'balance_sheet', 2),
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
        'ar': Account.objects.create(
            code='1100', name='العملاء', account_type=account_types['asset'], is_control=True
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
        'sales': Journal.objects.create(code='SALE', name='يومية المبيعات', type='sales'),
        'purchase': Journal.objects.create(code='PURCH', name='يومية المشتريات', type='purchases'),
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
def posted_invoice(db, accounts, journals, customer, project):
    """Create a posted invoice."""
    invoice = Invoice.objects.create(
        project=project,
        customer=customer,
        date=date.today(),
        due_date=date.today() + timedelta(days=30),
        description='دفعة للمشروع',
        amount=Decimal('50000.00'),
        amount_base=Decimal('50000.00'),
    )
    invoice.post()
    return invoice


@pytest.fixture
def posted_bill(db, accounts, journals, supplier, project):
    """Create a posted bill."""
    bill = Bill.objects.create(
        project=project,
        supplier=supplier,
        account=accounts['expense'],
        date=date.today(),
        due_date=date.today() + timedelta(days=30),
        description='توريد مواد',
        amount=Decimal('25000.00'),
        amount_base=Decimal('25000.00'),
    )
    bill.post()
    return bill


class TestInvoicePaymentStatus:
    """Test invoice payment status calculations."""

    def test_unpaid_invoice(self, posted_invoice):
        """Test status of unpaid invoice."""
        assert posted_invoice.amount_paid == Decimal('0.00')
        assert posted_invoice.amount_remaining == Decimal('50000.00')
        assert not posted_invoice.is_paid
        assert posted_invoice.payment_status == 'غير مدفوعة'

    def test_partially_paid_invoice(self, posted_invoice, accounts, customer):
        """Test status of partially paid invoice."""
        # Create and post payment
        payment = Payment.objects.create(
            direction='inbound',
            partner=customer,
            date=date.today(),
            account=accounts['cash'],
            amount=Decimal('20000.00'),
            amount_base=Decimal('20000.00'),
        )
        payment.post()

        # Allocate payment to invoice
        ct = ContentType.objects.get_for_model(Invoice)
        PaymentAllocation.objects.create(
            payment=payment,
            content_type=ct,
            object_id=posted_invoice.pk,
            amount=Decimal('20000.00')
        )

        # Check status
        assert posted_invoice.amount_paid == Decimal('20000.00')
        assert posted_invoice.amount_remaining == Decimal('30000.00')
        assert not posted_invoice.is_paid
        assert posted_invoice.payment_status == 'مدفوعة جزئياً'

    def test_fully_paid_invoice(self, posted_invoice, accounts, customer):
        """Test status of fully paid invoice."""
        # Create and post payment
        payment = Payment.objects.create(
            direction='inbound',
            partner=customer,
            date=date.today(),
            account=accounts['cash'],
            amount=Decimal('50000.00'),
            amount_base=Decimal('50000.00'),
        )
        payment.post()

        # Allocate full amount
        ct = ContentType.objects.get_for_model(Invoice)
        PaymentAllocation.objects.create(
            payment=payment,
            content_type=ct,
            object_id=posted_invoice.pk,
            amount=Decimal('50000.00')
        )

        # Check status
        assert posted_invoice.amount_paid == Decimal('50000.00')
        assert posted_invoice.amount_remaining == Decimal('0.00')
        assert posted_invoice.is_paid
        assert posted_invoice.payment_status == 'مدفوعة'

    def test_overdue_invoice(self, accounts, journals, customer, project):
        """Test status of overdue invoice."""
        # Create invoice with past due date
        invoice = Invoice.objects.create(
            project=project,
            customer=customer,
            date=date.today() - timedelta(days=40),
            due_date=date.today() - timedelta(days=10),  # Past due
            description='فاتورة متأخرة',
            amount=Decimal('30000.00'),
            amount_base=Decimal('30000.00'),
        )
        invoice.post()

        assert invoice.is_overdue
        assert invoice.payment_status == 'متأخرة'

    def test_paid_invoice_not_overdue(self, accounts, journals, customer, project):
        """Test that paid invoice is not marked overdue even if past due date."""
        # Create invoice with past due date
        invoice = Invoice.objects.create(
            project=project,
            customer=customer,
            date=date.today() - timedelta(days=40),
            due_date=date.today() - timedelta(days=10),  # Past due
            description='فاتورة متأخرة',
            amount=Decimal('30000.00'),
            amount_base=Decimal('30000.00'),
        )
        invoice.post()

        # Pay the invoice
        payment = Payment.objects.create(
            direction='inbound',
            partner=customer,
            date=date.today(),
            account=accounts['cash'],
            amount=Decimal('30000.00'),
            amount_base=Decimal('30000.00'),
        )
        payment.post()

        ct = ContentType.objects.get_for_model(Invoice)
        PaymentAllocation.objects.create(
            payment=payment,
            content_type=ct,
            object_id=invoice.pk,
            amount=Decimal('30000.00')
        )

        # Should not be overdue
        assert not invoice.is_overdue
        assert invoice.payment_status == 'مدفوعة'

    def test_multiple_payments(self, posted_invoice, accounts, customer):
        """Test invoice with multiple partial payments."""
        ct = ContentType.objects.get_for_model(Invoice)

        # First payment
        payment1 = Payment.objects.create(
            direction='inbound',
            partner=customer,
            date=date.today(),
            account=accounts['cash'],
            amount=Decimal('15000.00'),
            amount_base=Decimal('15000.00'),
        )
        payment1.post()
        PaymentAllocation.objects.create(
            payment=payment1,
            content_type=ct,
            object_id=posted_invoice.pk,
            amount=Decimal('15000.00')
        )

        assert posted_invoice.amount_paid == Decimal('15000.00')
        assert posted_invoice.amount_remaining == Decimal('35000.00')

        # Second payment
        payment2 = Payment.objects.create(
            direction='inbound',
            partner=customer,
            date=date.today(),
            account=accounts['cash'],
            amount=Decimal('35000.00'),
            amount_base=Decimal('35000.00'),
        )
        payment2.post()
        PaymentAllocation.objects.create(
            payment=payment2,
            content_type=ct,
            object_id=posted_invoice.pk,
            amount=Decimal('35000.00')
        )

        assert posted_invoice.amount_paid == Decimal('50000.00')
        assert posted_invoice.is_paid


class TestBillPaymentStatus:
    """Test bill payment status calculations."""

    def test_unpaid_bill(self, posted_bill):
        """Test status of unpaid bill."""
        assert posted_bill.amount_paid == Decimal('0.00')
        assert posted_bill.amount_remaining == Decimal('25000.00')
        assert not posted_bill.is_paid
        assert posted_bill.payment_status == 'غير مدفوعة'

    def test_partially_paid_bill(self, posted_bill, accounts, supplier):
        """Test status of partially paid bill."""
        # Create and post payment
        payment = Payment.objects.create(
            direction='outbound',
            partner=supplier,
            date=date.today(),
            account=accounts['cash'],
            amount=Decimal('10000.00'),
            amount_base=Decimal('10000.00'),
        )
        payment.post()

        # Allocate payment
        ct = ContentType.objects.get_for_model(Bill)
        PaymentAllocation.objects.create(
            payment=payment,
            content_type=ct,
            object_id=posted_bill.pk,
            amount=Decimal('10000.00')
        )

        assert posted_bill.amount_paid == Decimal('10000.00')
        assert posted_bill.amount_remaining == Decimal('15000.00')
        assert not posted_bill.is_paid
        assert posted_bill.payment_status == 'مدفوعة جزئياً'

    def test_fully_paid_bill(self, posted_bill, accounts, supplier):
        """Test status of fully paid bill."""
        # Create and post payment
        payment = Payment.objects.create(
            direction='outbound',
            partner=supplier,
            date=date.today(),
            account=accounts['cash'],
            amount=Decimal('25000.00'),
            amount_base=Decimal('25000.00'),
        )
        payment.post()

        # Allocate full amount
        ct = ContentType.objects.get_for_model(Bill)
        PaymentAllocation.objects.create(
            payment=payment,
            content_type=ct,
            object_id=posted_bill.pk,
            amount=Decimal('25000.00')
        )

        assert posted_bill.amount_paid == Decimal('25000.00')
        assert posted_bill.amount_remaining == Decimal('0.00')
        assert posted_bill.is_paid
        assert posted_bill.payment_status == 'مدفوعة'

    def test_overdue_bill(self, accounts, journals, supplier, project):
        """Test status of overdue bill."""
        bill = Bill.objects.create(
            project=project,
            supplier=supplier,
            account=accounts['expense'],
            date=date.today() - timedelta(days=40),
            due_date=date.today() - timedelta(days=5),  # Past due
            description='فاتورة مورد متأخرة',
            amount=Decimal('15000.00'),
            amount_base=Decimal('15000.00'),
        )
        bill.post()

        assert bill.is_overdue
        assert bill.payment_status == 'متأخرة'


class TestDraftDocuments:
    """Test that draft documents have correct status."""

    def test_draft_invoice_status(self, accounts, customer, project):
        """Test that draft invoice shows draft status."""
        invoice = Invoice.objects.create(
            project=project,
            customer=customer,
            date=date.today(),
            due_date=date.today() + timedelta(days=30),
            description='فاتورة مسودة',
            amount=Decimal('20000.00'),
            amount_base=Decimal('20000.00'),
            status='draft',
        )

        assert invoice.payment_status == 'مسودة'

    def test_draft_bill_status(self, accounts, supplier, project):
        """Test that draft bill shows draft status."""
        bill = Bill.objects.create(
            project=project,
            supplier=supplier,
            account=accounts['expense'],
            date=date.today(),
            due_date=date.today() + timedelta(days=30),
            description='فاتورة مورد مسودة',
            amount=Decimal('10000.00'),
            amount_base=Decimal('10000.00'),
            status='draft',
        )

        assert bill.payment_status == 'مسودة'


class TestDraftPaymentAllocation:
    """Test that draft payments don't affect allocation."""

    def test_draft_payment_not_counted(self, posted_invoice, accounts, customer):
        """Test that draft payment allocation doesn't count towards paid amount."""
        # Create draft payment (not posted)
        payment = Payment.objects.create(
            direction='inbound',
            partner=customer,
            date=date.today(),
            account=accounts['cash'],
            amount=Decimal('25000.00'),
            amount_base=Decimal('25000.00'),
            status='draft',  # Draft, not posted
        )

        # Allocate to invoice
        ct = ContentType.objects.get_for_model(Invoice)
        PaymentAllocation.objects.create(
            payment=payment,
            content_type=ct,
            object_id=posted_invoice.pk,
            amount=Decimal('25000.00')
        )

        # Draft payment should not affect amount_paid
        assert posted_invoice.amount_paid == Decimal('0.00')
        assert posted_invoice.amount_remaining == Decimal('50000.00')
