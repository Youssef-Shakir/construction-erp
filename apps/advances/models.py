"""
Cash Advance models for Construction ERP.

Handles:
- CashAdvance: Money given to employees for project expenses
- AdvanceReturn: Cash returned by employees
- Settlement: Derived from expenses and returns
"""
from decimal import Decimal
from django.db import models, transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Sum
from simple_history.models import HistoricalRecords

from apps.core.models import AuditMixin, Partner
from apps.projects.models import Project
from apps.accounting.models import Journal, JournalEntry, Account
from apps.accounting.posting import create_journal_entry, reverse_entry, PostingError


class CashAdvance(AuditMixin, models.Model):
    """
    Cash advance given to an employee for project expenses.

    Lifecycle: draft -> posted -> closed (or cancelled)
    Settlement is computed from linked expenses and returns.
    """
    STATUS_CHOICES = [
        ('draft', 'مسودة'),
        ('posted', 'مرحّل'),
        ('closed', 'مغلق'),
        ('cancelled', 'ملغي'),
    ]

    advance_number = models.CharField('رقم السلفة', max_length=50, unique=True, blank=True)
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name='advances',
        verbose_name='المشروع',
    )
    recipient = models.ForeignKey(
        Partner,
        on_delete=models.PROTECT,
        limit_choices_to={'type': 'employee'},
        related_name='advances_received',
        verbose_name='المستلم',
    )
    date = models.DateField('التاريخ')
    purpose = models.TextField('الغرض')

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
        related_name='cash_advance',
        verbose_name='القيد المحاسبي',
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'سلفة نقدية'
        verbose_name_plural = 'السلف النقدية'
        ordering = ['-date', '-advance_number']

    def __str__(self):
        return f'{self.advance_number} - {self.recipient.name}'

    def save(self, *args, **kwargs):
        # Auto-generate advance number
        if not self.advance_number:
            last = CashAdvance.objects.order_by('-id').first()
            next_num = (last.id + 1) if last else 1
            self.advance_number = f'ADV-{next_num:06d}'

        # Set amount_base = amount in V1 (single currency)
        if not self.amount_base:
            self.amount_base = self.amount

        super().save(*args, **kwargs)

    def clean(self):
        if self.amount <= 0:
            raise ValidationError('المبلغ يجب أن يكون أكبر من صفر')

    # Settlement calculations (all derived)
    @property
    def total_expenses(self):
        """Total posted expenses against this advance."""
        from apps.expenses.models import Expense
        result = Expense.objects.filter(
            advance=self,
            status='posted'
        ).aggregate(total=Sum('amount'))
        return result['total'] or Decimal('0.00')

    @property
    def total_returned(self):
        """Total cash returned against this advance."""
        result = self.returns.filter(
            status='posted'
        ).aggregate(total=Sum('amount'))
        return result['total'] or Decimal('0.00')

    @property
    def total_settled(self):
        """Total settled (expenses + returns)."""
        return self.total_expenses + self.total_returned

    @property
    def remaining(self):
        """Remaining unsettled amount."""
        return self.amount - self.total_settled

    @property
    def is_fully_settled(self):
        """Check if advance is fully settled."""
        return self.remaining == Decimal('0.00')

    def post(self, user=None):
        """
        Post the cash advance, creating the journal entry.

        Journal entry:
        - Debit: Advances to Project Managers (partner=recipient, project)
        - Credit: Cash
        """
        if self.status != 'draft':
            raise PostingError('يمكن ترحيل المسودات فقط')

        # Get required accounts
        try:
            advances_account = Account.objects.get(code='1200')  # Advances to PMs
            cash_account = Account.objects.get(code='1000')  # Cash
        except Account.DoesNotExist:
            raise PostingError('الحسابات المطلوبة غير موجودة. يرجى إعداد دليل الحسابات.')

        # Get cash journal
        try:
            journal = Journal.objects.get(code='CASH')
        except Journal.DoesNotExist:
            raise PostingError('يومية النقدية غير موجودة')

        with transaction.atomic():
            # Create journal entry
            lines = [
                {
                    'account': advances_account,
                    'debit': self.amount,
                    'partner': self.recipient,
                    'project': self.project,
                    'description': f'سلفة: {self.purpose[:50]}',
                },
                {
                    'account': cash_account,
                    'credit': self.amount,
                    'description': f'صرف سلفة {self.advance_number}',
                },
            ]

            entry = create_journal_entry(
                journal=journal,
                date=self.date,
                lines=lines,
                reference=self.advance_number,
                memo=f'سلفة نقدية - {self.recipient.name} - {self.project.name}',
                user=user,
                auto_post=True,
            )

            self.journal_entry = entry
            self.status = 'posted'
            self.save()

        return entry

    def cancel(self, user=None):
        """Cancel the advance by reversing the journal entry."""
        if self.status != 'posted':
            raise PostingError('يمكن إلغاء السلف المرحّلة فقط')

        if self.total_expenses > 0 or self.total_returned > 0:
            raise PostingError('لا يمكن إلغاء سلفة لها مصروفات أو مردودات')

        with transaction.atomic():
            if self.journal_entry:
                reverse_entry(self.journal_entry, self.date, user)

            self.status = 'cancelled'
            self.save()

    def close(self):
        """Close the advance after full settlement."""
        if self.status != 'posted':
            raise PostingError('يمكن إغلاق السلف المرحّلة فقط')

        if not self.is_fully_settled:
            raise PostingError('لا يمكن إغلاق سلفة غير مسوّاة بالكامل')

        self.status = 'closed'
        self.save()


class AdvanceReturn(AuditMixin, models.Model):
    """
    Cash returned by employee against an advance.

    Journal entry:
    - Debit: Cash
    - Credit: Advances to Project Managers (partner=advance.recipient)
    """
    STATUS_CHOICES = [
        ('draft', 'مسودة'),
        ('posted', 'مرحّل'),
        ('cancelled', 'ملغي'),
    ]

    return_number = models.CharField('رقم المردود', max_length=50, unique=True, blank=True)
    advance = models.ForeignKey(
        CashAdvance,
        on_delete=models.PROTECT,
        related_name='returns',
        verbose_name='السلفة',
    )
    date = models.DateField('التاريخ')

    # Amount fields
    amount = models.DecimalField('المبلغ', max_digits=18, decimal_places=2)
    currency = models.CharField('العملة', max_length=3, default='SAR')
    amount_base = models.DecimalField('المبلغ الأساسي', max_digits=18, decimal_places=2)

    notes = models.TextField('ملاحظات', blank=True)
    status = models.CharField('الحالة', max_length=20, choices=STATUS_CHOICES, default='draft')

    # Accounting link
    journal_entry = models.OneToOneField(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='advance_return',
        verbose_name='القيد المحاسبي',
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'مردود سلفة'
        verbose_name_plural = 'مردودات السلف'
        ordering = ['-date', '-return_number']

    def __str__(self):
        return f'{self.return_number} - {self.advance.advance_number}'

    def save(self, *args, **kwargs):
        if not self.return_number:
            last = AdvanceReturn.objects.order_by('-id').first()
            next_num = (last.id + 1) if last else 1
            self.return_number = f'RET-{next_num:06d}'

        if not self.amount_base:
            self.amount_base = self.amount

        super().save(*args, **kwargs)

    def clean(self):
        if self.amount <= 0:
            raise ValidationError('المبلغ يجب أن يكون أكبر من صفر')

        # Can't return more than remaining
        if self.advance and self.amount > self.advance.remaining:
            raise ValidationError(f'المبلغ المردود ({self.amount}) أكبر من المتبقي ({self.advance.remaining})')

    def post(self, user=None):
        """Post the return, creating journal entry."""
        if self.status != 'draft':
            raise PostingError('يمكن ترحيل المسودات فقط')

        if self.advance.status != 'posted':
            raise PostingError('السلفة يجب أن تكون مرحّلة')

        try:
            advances_account = Account.objects.get(code='1200')
            cash_account = Account.objects.get(code='1000')
        except Account.DoesNotExist:
            raise PostingError('الحسابات المطلوبة غير موجودة')

        try:
            journal = Journal.objects.get(code='CASH')
        except Journal.DoesNotExist:
            raise PostingError('يومية النقدية غير موجودة')

        with transaction.atomic():
            lines = [
                {
                    'account': cash_account,
                    'debit': self.amount,
                    'description': f'استلام مردود سلفة {self.advance.advance_number}',
                },
                {
                    'account': advances_account,
                    'credit': self.amount,
                    'partner': self.advance.recipient,
                    'project': self.advance.project,
                    'description': f'مردود سلفة',
                },
            ]

            entry = create_journal_entry(
                journal=journal,
                date=self.date,
                lines=lines,
                reference=self.return_number,
                memo=f'مردود سلفة - {self.advance.advance_number}',
                user=user,
                auto_post=True,
            )

            self.journal_entry = entry
            self.status = 'posted'
            self.save()

        return entry
