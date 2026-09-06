"""
Expense models for Construction ERP.

Handles:
- Expense: Can be advance-linked, direct project, or company expense
- PaperReceipt: Register for tracking physical receipts
"""
from decimal import Decimal
from django.db import models, transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from simple_history.models import HistoricalRecords

from apps.core.models import AuditMixin, Partner
from apps.projects.models import Project
from apps.advances.models import CashAdvance
from apps.accounting.models import Journal, JournalEntry, Account
from apps.accounting.posting import create_journal_entry, reverse_entry, PostingError


class Expense(AuditMixin, models.Model):
    """
    Expense record.

    Types (determined by fields):
    - Advance-linked: advance is set (credits Advances to PMs)
    - Direct project: project is set, advance is null (credits Cash)
    - Company: project is null, advance is null (credits Cash)
    """
    STATUS_CHOICES = [
        ('draft', 'مسودة'),
        ('posted', 'مرحّل'),
        ('cancelled', 'ملغي'),
    ]

    expense_number = models.CharField('رقم المصروف', max_length=50, unique=True, blank=True)
    date = models.DateField('التاريخ')

    # Optional links
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='expenses',
        verbose_name='المشروع',
    )
    advance = models.ForeignKey(
        CashAdvance,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='expenses',
        verbose_name='السلفة',
    )

    # Expense details
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        limit_choices_to={'account_type__code': 'expense'},
        related_name='expenses',
        verbose_name='حساب المصروف',
    )
    partner = models.ForeignKey(
        Partner,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expenses',
        verbose_name='المورد',
    )
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
        related_name='expense',
        verbose_name='القيد المحاسبي',
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'مصروف'
        verbose_name_plural = 'المصروفات'
        ordering = ['-date', '-expense_number']

    def __str__(self):
        return f'{self.expense_number} - {self.description[:30]}'

    def save(self, *args, **kwargs):
        if not self.expense_number:
            last = Expense.objects.order_by('-id').first()
            next_num = (last.id + 1) if last else 1
            self.expense_number = f'EXP-{next_num:06d}'

        if not self.amount_base:
            self.amount_base = self.amount

        super().save(*args, **kwargs)

    def clean(self):
        if self.amount <= 0:
            raise ValidationError('المبلغ يجب أن يكون أكبر من صفر')

        # If advance is set, project must match
        if self.advance and self.project and self.advance.project != self.project:
            raise ValidationError('المشروع يجب أن يتطابق مع مشروع السلفة')

        # If advance is set, use its project
        if self.advance and not self.project:
            self.project = self.advance.project

        # Can't exceed advance remaining
        if self.advance:
            remaining = self.advance.remaining
            if self.pk:  # Editing existing
                existing = Expense.objects.get(pk=self.pk)
                if existing.status == 'posted':
                    remaining += existing.amount
            if self.amount > remaining:
                raise ValidationError(f'المبلغ ({self.amount}) أكبر من المتبقي في السلفة ({remaining})')

    @property
    def expense_type(self):
        """Return expense type for display."""
        if self.advance:
            return 'سلفة'
        elif self.project:
            return 'مشروع'
        else:
            return 'شركة'

    def post(self, user=None):
        """
        Post the expense, creating the journal entry.

        If advance-linked:
        - Debit: Expense account (project)
        - Credit: Advances to PMs (partner=advance.recipient)

        If direct (no advance):
        - Debit: Expense account (project or none)
        - Credit: Cash
        """
        if self.status != 'draft':
            raise PostingError('يمكن ترحيل المسودات فقط')

        if self.advance and self.advance.status != 'posted':
            raise PostingError('السلفة يجب أن تكون مرحّلة')

        # Get accounts
        try:
            if self.advance:
                credit_account = Account.objects.get(code='1200')  # Advances to PMs
                credit_partner = self.advance.recipient
            else:
                credit_account = Account.objects.get(code='1000')  # Cash
                credit_partner = None
        except Account.DoesNotExist:
            raise PostingError('الحسابات المطلوبة غير موجودة')

        # Get journal
        try:
            journal = Journal.objects.get(code='CASH')
        except Journal.DoesNotExist:
            raise PostingError('يومية النقدية غير موجودة')

        with transaction.atomic():
            lines = [
                {
                    'account': self.account,
                    'debit': self.amount,
                    'partner': self.partner,
                    'project': self.project,
                    'description': self.description[:100],
                },
                {
                    'account': credit_account,
                    'credit': self.amount,
                    'partner': credit_partner,
                    'project': self.project if self.advance else None,
                    'description': f'مصروف {self.expense_number}',
                },
            ]

            entry = create_journal_entry(
                journal=journal,
                date=self.date,
                lines=lines,
                reference=self.expense_number,
                memo=f'مصروف - {self.description[:50]}',
                user=user,
                auto_post=True,
            )

            self.journal_entry = entry
            self.status = 'posted'
            self.save()

        return entry

    def cancel(self, user=None):
        """Cancel the expense by reversing the journal entry."""
        if self.status != 'posted':
            raise PostingError('يمكن إلغاء المصروفات المرحّلة فقط')

        with transaction.atomic():
            if self.journal_entry:
                reverse_entry(self.journal_entry, self.date, user)

            self.status = 'cancelled'
            self.save()


class PaperReceipt(models.Model):
    """
    Register for tracking physical receipts.
    Receipts can be matched to expenses later.
    """
    receipt_number = models.CharField('رقم الإيصال', max_length=50, unique=True, blank=True)
    expense = models.ForeignKey(
        Expense,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='receipts',
        verbose_name='المصروف',
    )

    vendor_name = models.CharField('اسم المورد', max_length=255)
    date = models.DateField('تاريخ الإيصال')
    amount = models.DecimalField('المبلغ', max_digits=18, decimal_places=2)
    description = models.CharField('الوصف', max_length=255, blank=True)

    received_from = models.ForeignKey(
        Partner,
        on_delete=models.SET_NULL,
        null=True,
        limit_choices_to={'type': 'employee'},
        related_name='submitted_receipts',
        verbose_name='مستلم من',
    )
    received_at = models.DateTimeField('تاريخ الاستلام', auto_now_add=True)
    matched = models.BooleanField('تم المطابقة', default=False)
    notes = models.TextField('ملاحظات', blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'إيصال ورقي'
        verbose_name_plural = 'الإيصالات الورقية'
        ordering = ['-date', '-receipt_number']

    def __str__(self):
        return f'{self.receipt_number} - {self.vendor_name}'

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            last = PaperReceipt.objects.order_by('-id').first()
            next_num = (last.id + 1) if last else 1
            self.receipt_number = f'RCP-{next_num:06d}'

        # Auto-match status
        if self.expense:
            self.matched = True

        super().save(*args, **kwargs)
