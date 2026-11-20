"""
Accounting models: AccountType, Account, Journal, JournalEntry, JournalLine.

The accounting app is agnostic of construction domain. It only enforces
debits == credits and provides the ledger infrastructure.
"""
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from simple_history.models import HistoricalRecords


class AccountType(models.Model):
    """
    Account types: Asset, Liability, Equity, Revenue, Expense.
    Determines normal balance (debit/credit) and report placement.
    """
    NORMAL_BALANCE_CHOICES = [
        ('debit', 'مدين'),
        ('credit', 'دائن'),
    ]
    REPORT_SECTION_CHOICES = [
        ('balance_sheet', 'الميزانية العمومية'),
        ('income_statement', 'قائمة الدخل'),
    ]

    code = models.CharField('الرمز', max_length=20, unique=True)
    name = models.CharField('الاسم', max_length=100)
    name_en = models.CharField('الاسم بالإنجليزية', max_length=100, blank=True)
    normal_balance = models.CharField('الرصيد الطبيعي', max_length=10, choices=NORMAL_BALANCE_CHOICES)
    report_section = models.CharField('القسم في التقارير', max_length=20, choices=REPORT_SECTION_CHOICES)
    order = models.PositiveIntegerField('الترتيب', default=0)

    class Meta:
        verbose_name = 'نوع الحساب'
        verbose_name_plural = 'أنواع الحسابات'
        ordering = ['order', 'code']

    def __str__(self):
        return self.name


class Account(models.Model):
    """
    Chart of accounts entry.
    Supports hierarchical structure via parent FK.
    Control accounts (AR, AP, Advances) are flagged for special handling.
    """
    code = models.CharField('رمز الحساب', max_length=20, unique=True)
    name = models.CharField('اسم الحساب', max_length=255)
    name_en = models.CharField('الاسم بالإنجليزية', max_length=255, blank=True)
    account_type = models.ForeignKey(
        AccountType,
        on_delete=models.PROTECT,
        related_name='accounts',
        verbose_name='نوع الحساب',
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name='الحساب الأب',
    )
    is_control = models.BooleanField(
        'حساب رقابي',
        default=False,
        help_text='حسابات المدينين والدائنين والسلف - لا يمكن استخدامها مباشرة'
    )
    is_active = models.BooleanField('نشط', default=True)
    description = models.TextField('الوصف', blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'حساب'
        verbose_name_plural = 'الحسابات'
        ordering = ['code']

    def __str__(self):
        return f'{self.code} - {self.name}'

    @property
    def balance(self):
        """Calculate current balance from journal lines."""
        from django.db.models import Sum
        result = self.journal_lines.filter(
            entry__is_posted=True
        ).aggregate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit')
        )
        debit = result['total_debit'] or Decimal('0.00')
        credit = result['total_credit'] or Decimal('0.00')

        if self.account_type.normal_balance == 'debit':
            return debit - credit
        return credit - debit

    def get_balance_at_date(self, as_of_date, project=None):
        """
        Calculate balance as of a specific date.

        Pass `project` to scope the balance to journal lines tagged with
        that project only (used for per-project income statements).
        """
        from django.db.models import Sum
        lines = self.journal_lines.filter(
            entry__is_posted=True,
            entry__date__lte=as_of_date
        )
        if project is not None:
            lines = lines.filter(project=project)
        result = lines.aggregate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit')
        )
        debit = result['total_debit'] or Decimal('0.00')
        credit = result['total_credit'] or Decimal('0.00')

        if self.account_type.normal_balance == 'debit':
            return debit - credit
        return credit - debit


class Journal(models.Model):
    """
    Journals group related entries (Cash, Bank, Sales, Purchases, General).
    """
    JOURNAL_TYPES = [
        ('cash', 'يومية النقدية'),
        ('bank', 'يومية البنك'),
        ('sales', 'يومية المبيعات'),
        ('purchases', 'يومية المشتريات'),
        ('general', 'يومية عامة'),
    ]

    code = models.CharField('الرمز', max_length=20, unique=True)
    name = models.CharField('الاسم', max_length=100)
    type = models.CharField('النوع', max_length=20, choices=JOURNAL_TYPES)
    default_debit_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='default_debit_journals',
        verbose_name='الحساب المدين الافتراضي',
    )
    default_credit_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='default_credit_journals',
        verbose_name='الحساب الدائن الافتراضي',
    )
    is_active = models.BooleanField('نشط', default=True)
    next_number = models.PositiveIntegerField('الرقم التالي', default=1)

    class Meta:
        verbose_name = 'يومية'
        verbose_name_plural = 'اليوميات'
        ordering = ['code']

    def __str__(self):
        return f'{self.code} - {self.name}'

    def get_next_entry_number(self):
        """Generate next entry number and increment counter."""
        number = f'{self.code}-{self.next_number:06d}'
        self.next_number += 1
        self.save(update_fields=['next_number'])
        return number


class JournalEntry(models.Model):
    """
    A journal entry with multiple lines.
    Enforces debits == credits when posted.
    Immutable once posted (corrections via reversals only).
    """
    journal = models.ForeignKey(
        Journal,
        on_delete=models.PROTECT,
        related_name='entries',
        verbose_name='اليومية',
    )
    entry_number = models.CharField('رقم القيد', max_length=50, unique=True)
    date = models.DateField('التاريخ')
    reference = models.CharField('المرجع', max_length=100, blank=True)
    memo = models.TextField('البيان', blank=True)

    # Posting status
    is_posted = models.BooleanField('مرحّل', default=False)
    posted_at = models.DateTimeField('تاريخ الترحيل', null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posted_entries',
        verbose_name='رُحّل بواسطة',
    )

    # Reversal tracking
    is_reversed = models.BooleanField('ملغي', default=False)
    reversed_by = models.OneToOneField(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversal_of',
        verbose_name='ألغي بواسطة',
    )
    reverses = models.OneToOneField(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversed_entry',
        verbose_name='إلغاء لـ',
    )

    # Audit
    created_at = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_entries',
        verbose_name='أنشئ بواسطة',
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'قيد يومية'
        verbose_name_plural = 'قيود اليومية'
        ordering = ['-date', '-entry_number']

    def __str__(self):
        return f'{self.entry_number} - {self.date}'

    def clean(self):
        """Validate entry before saving."""
        if self.pk and self.is_posted:
            # Check if we're trying to modify a posted entry
            old = JournalEntry.objects.get(pk=self.pk)
            if old.is_posted:
                # Only allow updating reversal fields
                mutable_fields = {'is_reversed', 'reversed_by'}
                for field in self._meta.fields:
                    if field.name not in mutable_fields and field.name not in ['id', 'history']:
                        old_val = getattr(old, field.name)
                        new_val = getattr(self, field.name)
                        if old_val != new_val:
                            raise ValidationError('لا يمكن تعديل قيد مرحّل')

    @property
    def total_debit(self):
        """Sum of all debit amounts."""
        return sum(line.debit for line in self.lines.all())

    @property
    def total_credit(self):
        """Sum of all credit amounts."""
        return sum(line.credit for line in self.lines.all())

    @property
    def is_balanced(self):
        """Check if debits equal credits."""
        return self.total_debit == self.total_credit


class JournalLine(models.Model):
    """
    A single line in a journal entry.
    Each line debits OR credits an account (not both).
    """
    entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name='lines',
        verbose_name='القيد',
    )
    line_number = models.PositiveIntegerField('رقم السطر', default=1)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='journal_lines',
        verbose_name='الحساب',
    )
    description = models.CharField('الوصف', max_length=255, blank=True)
    debit = models.DecimalField('مدين', max_digits=18, decimal_places=2, default=Decimal('0.00'))
    credit = models.DecimalField('دائن', max_digits=18, decimal_places=2, default=Decimal('0.00'))

    # Sub-ledger references (for control accounts)
    partner = models.ForeignKey(
        'core.Partner',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_lines',
        verbose_name='الشريك',
    )
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_lines',
        verbose_name='المشروع',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'سطر قيد'
        verbose_name_plural = 'سطور القيود'
        ordering = ['entry', 'line_number']

    def __str__(self):
        if self.debit > 0:
            return f'{self.account.code} - مدين {self.debit}'
        return f'{self.account.code} - دائن {self.credit}'

    def clean(self):
        """Validate line."""
        if self.debit > 0 and self.credit > 0:
            raise ValidationError('لا يمكن أن يكون السطر مدين ودائن في نفس الوقت')
        if self.debit == 0 and self.credit == 0:
            raise ValidationError('يجب تحديد مبلغ مدين أو دائن')
        if self.debit < 0 or self.credit < 0:
            raise ValidationError('لا يمكن أن يكون المبلغ سالباً')

        # Control accounts require partner
        if self.account.is_control and not self.partner:
            raise ValidationError('الحسابات الرقابية تتطلب تحديد الشريك')
