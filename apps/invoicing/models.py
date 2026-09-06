"""
Invoicing models for Construction ERP.

Handles:
- Invoice: Customer invoices (Accounts Receivable)
- Bill: Supplier bills (Accounts Payable)
"""
from decimal import Decimal
from django.db import models, transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.core.models import AuditMixin, Partner
from apps.projects.models import Project
from apps.accounting.models import Journal, JournalEntry, Account
from apps.accounting.posting import create_journal_entry, reverse_entry, PostingError


class Invoice(AuditMixin, models.Model):
    """
    Customer invoice (Accounts Receivable).

    Journal entry when posted:
    - Debit: Accounts Receivable (partner=customer, project)
    - Credit: Revenue (project)
    """
    STATUS_CHOICES = [
        ('draft', 'مسودة'),
        ('posted', 'مرحّل'),
        ('cancelled', 'ملغي'),
    ]

    invoice_number = models.CharField('رقم الفاتورة', max_length=50, unique=True, blank=True)
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name='invoices',
        verbose_name='المشروع',
    )
    customer = models.ForeignKey(
        Partner,
        on_delete=models.PROTECT,
        limit_choices_to={'type': 'customer'},
        related_name='invoices',
        verbose_name='العميل',
    )
    date = models.DateField('تاريخ الفاتورة')
    due_date = models.DateField('تاريخ الاستحقاق')
    description = models.TextField('الوصف')

    # Amount fields
    amount = models.DecimalField('المبلغ', max_digits=18, decimal_places=2)
    currency = models.CharField('العملة', max_length=3, default='SAR')
    amount_base = models.DecimalField('المبلغ الأساسي', max_digits=18, decimal_places=2)

    status = models.CharField('الحالة', max_length=20, choices=STATUS_CHOICES, default='draft')

    # Accounting link
    journal_entry = models.OneToOneField(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice',
        verbose_name='القيد المحاسبي',
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'فاتورة'
        verbose_name_plural = 'الفواتير'
        ordering = ['-date', '-invoice_number']

    def __str__(self):
        return f'{self.invoice_number} - {self.customer.name}'

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            last = Invoice.objects.order_by('-id').first()
            next_num = (last.id + 1) if last else 1
            self.invoice_number = f'INV-{next_num:06d}'

        if not self.amount_base:
            self.amount_base = self.amount

        super().save(*args, **kwargs)

    def clean(self):
        if self.amount <= 0:
            raise ValidationError('المبلغ يجب أن يكون أكبر من صفر')
        if self.due_date and self.date and self.due_date < self.date:
            raise ValidationError('تاريخ الاستحقاق يجب أن يكون بعد تاريخ الفاتورة')

    @property
    def amount_paid(self):
        """Total amount paid via payment allocations."""
        from apps.payments.models import PaymentAllocation
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(self)
        result = PaymentAllocation.objects.filter(
            content_type=ct,
            object_id=self.pk,
            payment__status='posted'
        ).aggregate(total=Sum('amount'))
        return result['total'] or Decimal('0.00')

    @property
    def amount_remaining(self):
        """Remaining unpaid amount."""
        return self.amount - self.amount_paid

    @property
    def is_paid(self):
        """Check if invoice is fully paid."""
        return self.amount_remaining == Decimal('0.00')

    @property
    def is_overdue(self):
        """Check if invoice is overdue."""
        if self.is_paid:
            return False
        return self.due_date < timezone.now().date()

    @property
    def payment_status(self):
        """Return payment status for display."""
        if self.status != 'posted':
            return self.get_status_display()
        if self.is_paid:
            return 'مدفوعة'
        if self.is_overdue:
            return 'متأخرة'
        if self.amount_paid > 0:
            return 'مدفوعة جزئياً'
        return 'غير مدفوعة'

    def post(self, user=None):
        """Post the invoice, creating journal entry."""
        if self.status != 'draft':
            raise PostingError('يمكن ترحيل المسودات فقط')

        try:
            ar_account = Account.objects.get(code='1100')  # Accounts Receivable
            revenue_account = Account.objects.get(code='4000')  # Revenue
        except Account.DoesNotExist:
            raise PostingError('الحسابات المطلوبة غير موجودة')

        try:
            journal = Journal.objects.get(code='SALE')
        except Journal.DoesNotExist:
            raise PostingError('يومية المبيعات غير موجودة')

        with transaction.atomic():
            lines = [
                {
                    'account': ar_account,
                    'debit': self.amount,
                    'partner': self.customer,
                    'project': self.project,
                    'description': f'فاتورة {self.invoice_number}',
                },
                {
                    'account': revenue_account,
                    'credit': self.amount,
                    'project': self.project,
                    'description': self.description[:100],
                },
            ]

            entry = create_journal_entry(
                journal=journal,
                date=self.date,
                lines=lines,
                reference=self.invoice_number,
                memo=f'فاتورة مبيعات - {self.customer.name}',
                user=user,
                auto_post=True,
            )

            self.journal_entry = entry
            self.status = 'posted'
            self.save()

        return entry

    def cancel(self, user=None):
        """Cancel the invoice."""
        if self.status != 'posted':
            raise PostingError('يمكن إلغاء الفواتير المرحّلة فقط')

        if self.amount_paid > 0:
            raise PostingError('لا يمكن إلغاء فاتورة لها مدفوعات')

        with transaction.atomic():
            if self.journal_entry:
                reverse_entry(self.journal_entry, self.date, user)

            self.status = 'cancelled'
            self.save()


class Bill(AuditMixin, models.Model):
    """
    Supplier bill (Accounts Payable).

    Journal entry when posted:
    - Debit: Expense account (project or none)
    - Credit: Accounts Payable (partner=supplier, project)
    """
    STATUS_CHOICES = [
        ('draft', 'مسودة'),
        ('posted', 'مرحّل'),
        ('cancelled', 'ملغي'),
    ]

    bill_number = models.CharField('رقم الفاتورة', max_length=50, unique=True, blank=True)
    vendor_reference = models.CharField('مرجع المورد', max_length=100, blank=True)

    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='bills',
        verbose_name='المشروع',
    )
    supplier = models.ForeignKey(
        Partner,
        on_delete=models.PROTECT,
        limit_choices_to={'type': 'supplier'},
        related_name='bills',
        verbose_name='المورد',
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        limit_choices_to={'account_type__code': 'expense'},
        related_name='bills',
        verbose_name='حساب المصروف',
    )

    date = models.DateField('تاريخ الفاتورة')
    due_date = models.DateField('تاريخ الاستحقاق')
    description = models.TextField('الوصف')

    # Amount fields
    amount = models.DecimalField('المبلغ', max_digits=18, decimal_places=2)
    currency = models.CharField('العملة', max_length=3, default='SAR')
    amount_base = models.DecimalField('المبلغ الأساسي', max_digits=18, decimal_places=2)

    status = models.CharField('الحالة', max_length=20, choices=STATUS_CHOICES, default='draft')

    # Accounting link
    journal_entry = models.OneToOneField(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bill',
        verbose_name='القيد المحاسبي',
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'فاتورة مورد'
        verbose_name_plural = 'فواتير الموردين'
        ordering = ['-date', '-bill_number']

    def __str__(self):
        return f'{self.bill_number} - {self.supplier.name}'

    def save(self, *args, **kwargs):
        if not self.bill_number:
            last = Bill.objects.order_by('-id').first()
            next_num = (last.id + 1) if last else 1
            self.bill_number = f'BILL-{next_num:06d}'

        if not self.amount_base:
            self.amount_base = self.amount

        super().save(*args, **kwargs)

    def clean(self):
        if self.amount <= 0:
            raise ValidationError('المبلغ يجب أن يكون أكبر من صفر')
        if self.due_date and self.date and self.due_date < self.date:
            raise ValidationError('تاريخ الاستحقاق يجب أن يكون بعد تاريخ الفاتورة')

    @property
    def amount_paid(self):
        """Total amount paid via payment allocations."""
        from apps.payments.models import PaymentAllocation
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(self)
        result = PaymentAllocation.objects.filter(
            content_type=ct,
            object_id=self.pk,
            payment__status='posted'
        ).aggregate(total=Sum('amount'))
        return result['total'] or Decimal('0.00')

    @property
    def amount_remaining(self):
        """Remaining unpaid amount."""
        return self.amount - self.amount_paid

    @property
    def is_paid(self):
        """Check if bill is fully paid."""
        return self.amount_remaining == Decimal('0.00')

    @property
    def is_overdue(self):
        """Check if bill is overdue."""
        if self.is_paid:
            return False
        return self.due_date < timezone.now().date()

    @property
    def payment_status(self):
        """Return payment status for display."""
        if self.status != 'posted':
            return self.get_status_display()
        if self.is_paid:
            return 'مدفوعة'
        if self.is_overdue:
            return 'متأخرة'
        if self.amount_paid > 0:
            return 'مدفوعة جزئياً'
        return 'غير مدفوعة'

    def post(self, user=None):
        """Post the bill, creating journal entry."""
        if self.status != 'draft':
            raise PostingError('يمكن ترحيل المسودات فقط')

        try:
            ap_account = Account.objects.get(code='2000')  # Accounts Payable
        except Account.DoesNotExist:
            raise PostingError('حساب الدائنين غير موجود')

        try:
            journal = Journal.objects.get(code='PURCH')
        except Journal.DoesNotExist:
            raise PostingError('يومية المشتريات غير موجودة')

        with transaction.atomic():
            lines = [
                {
                    'account': self.account,
                    'debit': self.amount,
                    'partner': self.supplier,
                    'project': self.project,
                    'description': self.description[:100],
                },
                {
                    'account': ap_account,
                    'credit': self.amount,
                    'partner': self.supplier,
                    'project': self.project,
                    'description': f'فاتورة {self.bill_number}',
                },
            ]

            entry = create_journal_entry(
                journal=journal,
                date=self.date,
                lines=lines,
                reference=self.bill_number,
                memo=f'فاتورة مورد - {self.supplier.name}',
                user=user,
                auto_post=True,
            )

            self.journal_entry = entry
            self.status = 'posted'
            self.save()

        return entry

    def cancel(self, user=None):
        """Cancel the bill."""
        if self.status != 'posted':
            raise PostingError('يمكن إلغاء الفواتير المرحّلة فقط')

        if self.amount_paid > 0:
            raise PostingError('لا يمكن إلغاء فاتورة لها مدفوعات')

        with transaction.atomic():
            if self.journal_entry:
                reverse_entry(self.journal_entry, self.date, user)

            self.status = 'cancelled'
            self.save()
