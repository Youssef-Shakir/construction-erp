"""
Payment models for Construction ERP.

Handles:
- Payment: Inbound (from customers) and outbound (to suppliers)
- PaymentAllocation: Links payments to invoices/bills
"""
from decimal import Decimal
from django.db import models, transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from simple_history.models import HistoricalRecords

from apps.core.models import AuditMixin, Partner
from apps.core.sequences import next_document_number
from apps.accounting.models import Journal, JournalEntry, Account
from apps.accounting.posting import create_journal_entry, reverse_entry, PostingError, locked_document


class Payment(AuditMixin, models.Model):
    """
    Payment record (inbound or outbound).

    Inbound: Money received from customer
    - Debit: Cash/Bank
    - Credit: Accounts Receivable (partner)

    Outbound: Money paid to supplier
    - Debit: Accounts Payable (partner)
    - Credit: Cash/Bank
    """
    DIRECTION_CHOICES = [
        ('inbound', 'وارد'),
        ('outbound', 'صادر'),
    ]
    STATUS_CHOICES = [
        ('draft', 'مسودة'),
        ('posted', 'مرحّل'),
        ('cancelled', 'ملغي'),
    ]

    payment_number = models.CharField('رقم الدفعة', max_length=50, unique=True, blank=True)
    direction = models.CharField('الاتجاه', max_length=20, choices=DIRECTION_CHOICES)
    partner = models.ForeignKey(
        Partner,
        on_delete=models.PROTECT,
        related_name='payments',
        verbose_name='الشريك',
    )
    date = models.DateField('التاريخ')

    # Payment account (Cash or Bank)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='payments',
        verbose_name='الحساب',
        help_text='حساب النقدية أو البنك',
    )

    # Amount
    amount = models.DecimalField('المبلغ', max_digits=18, decimal_places=2)
    currency = models.CharField('العملة', max_length=3, default='SAR')
    amount_base = models.DecimalField('المبلغ الأساسي', max_digits=18, decimal_places=2)

    reference = models.CharField('المرجع', max_length=100, blank=True, help_text='رقم الشيك أو الحوالة')
    memo = models.TextField('ملاحظات', blank=True)

    status = models.CharField('الحالة', max_length=20, choices=STATUS_CHOICES, default='draft')

    # Accounting link
    journal_entry = models.OneToOneField(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment',
        verbose_name='القيد المحاسبي',
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'دفعة'
        verbose_name_plural = 'المدفوعات'
        ordering = ['-date', '-payment_number']

    def __str__(self):
        direction = 'وارد' if self.direction == 'inbound' else 'صادر'
        return f'{self.payment_number} - {direction} - {self.partner.name}'

    def save(self, *args, **kwargs):
        if not self.payment_number:
            prefix = 'PMT-IN' if self.direction == 'inbound' else 'PMT-OUT'
            self.payment_number = next_document_number(prefix, Payment, 'payment_number')

        if not self.amount_base:
            self.amount_base = self.amount

        super().save(*args, **kwargs)

    def clean(self):
        if self.amount <= 0:
            raise ValidationError('المبلغ يجب أن يكون أكبر من صفر')

        # Validate partner type based on direction
        if self.partner:
            if self.direction == 'inbound' and self.partner.type != 'customer':
                raise ValidationError('الدفعات الواردة يجب أن تكون من عميل')
            if self.direction == 'outbound' and self.partner.type != 'supplier':
                raise ValidationError('الدفعات الصادرة يجب أن تكون لمورد')

    @property
    def allocated_amount(self):
        """Total amount allocated to invoices/bills."""
        result = self.allocations.aggregate(total=Sum('amount'))
        return result['total'] or Decimal('0.00')

    @property
    def unallocated_amount(self):
        """Remaining unallocated amount."""
        return self.amount - self.allocated_amount

    @locked_document
    def post(self, user=None):
        """Post the payment, creating journal entry."""
        if self.status != 'draft':
            raise PostingError('يمكن ترحيل المسودات فقط')

        # Control account based on direction
        try:
            control_account = Account.objects.get(code='1100' if self.direction == 'inbound' else '2000')
        except Account.DoesNotExist:
            raise PostingError('الحسابات المطلوبة غير موجودة')

        # Journal: the cash/bank journal whose default account is the payment
        # account (so bank payments land in the bank journal), else the cash one.
        cash_like = Journal.objects.filter(is_active=True, type__in=['cash', 'bank'])
        journal = (
            cash_like.filter(
                models.Q(default_debit_account=self.account) | models.Q(default_credit_account=self.account)
            ).order_by('code').first()
            or cash_like.filter(type='cash').order_by('code').first()
        )
        if journal is None:
            raise PostingError('يومية النقدية غير موجودة')

        with transaction.atomic():
            if self.direction == 'inbound':
                # Debit Cash, Credit AR
                lines = [
                    {
                        'account': self.account,
                        'debit': self.amount,
                        'description': f'استلام دفعة {self.payment_number}',
                    },
                    {
                        'account': control_account,
                        'credit': self.amount,
                        'partner': self.partner,
                        'description': f'دفعة من {self.partner.name}',
                    },
                ]
            else:
                # Debit AP, Credit Cash
                lines = [
                    {
                        'account': control_account,
                        'debit': self.amount,
                        'partner': self.partner,
                        'description': f'دفعة لـ {self.partner.name}',
                    },
                    {
                        'account': self.account,
                        'credit': self.amount,
                        'description': f'صرف دفعة {self.payment_number}',
                    },
                ]

            entry = create_journal_entry(
                journal=journal,
                date=self.date,
                lines=lines,
                reference=self.payment_number,
                memo=self.memo or f'دفعة - {self.partner.name}',
                user=user,
                auto_post=True,
            )

            self.journal_entry = entry
            self.status = 'posted'
            self.save()

        return entry

    @locked_document
    def cancel(self, user=None):
        """Cancel the payment."""
        if self.status != 'posted':
            raise PostingError('يمكن إلغاء المدفوعات المرحّلة فقط')

        # Check if there are allocations
        if self.allocations.exists():
            raise PostingError('لا يمكن إلغاء دفعة لها تخصيصات')

        with transaction.atomic():
            if self.journal_entry:
                reverse_entry(self.journal_entry, self.date, user)

            self.status = 'cancelled'
            self.save()


class PaymentAllocation(models.Model):
    """
    Allocation of payment to invoice or bill.
    Uses GenericForeignKey to support both Invoice and Bill.
    """
    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='allocations',
        verbose_name='الدفعة',
    )

    # Generic relation to Invoice or Bill
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    document = GenericForeignKey('content_type', 'object_id')

    amount = models.DecimalField('المبلغ', max_digits=18, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'تخصيص دفعة'
        verbose_name_plural = 'تخصيصات المدفوعات'

    def __str__(self):
        return f'{self.payment.payment_number} -> {self.amount}'

    def clean(self):
        if self.amount <= 0:
            raise ValidationError('المبلغ يجب أن يكون أكبر من صفر')

        # Validate direction matches document type
        from apps.invoicing.models import Invoice, Bill

        if self.payment.direction == 'inbound':
            if not isinstance(self.document, Invoice):
                raise ValidationError('الدفعات الواردة تُخصص للفواتير فقط')
        else:
            if not isinstance(self.document, Bill):
                raise ValidationError('الدفعات الصادرة تُخصص لفواتير الموردين فقط')

        # Check allocation doesn't exceed payment amount
        existing = self.payment.allocations.exclude(pk=self.pk).aggregate(total=Sum('amount'))
        existing_total = existing['total'] or Decimal('0.00')
        if existing_total + self.amount > self.payment.amount:
            raise ValidationError('إجمالي التخصيصات يتجاوز مبلغ الدفعة')

        # Check allocation doesn't exceed document amount
        doc_allocations = PaymentAllocation.objects.filter(
            content_type=self.content_type,
            object_id=self.object_id
        ).exclude(pk=self.pk).aggregate(total=Sum('amount'))
        doc_total = doc_allocations['total'] or Decimal('0.00')
        if doc_total + self.amount > self.document.amount:
            raise ValidationError('إجمالي التخصيصات يتجاوز مبلغ المستند')
