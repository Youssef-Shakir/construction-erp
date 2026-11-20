"""
Project model for Construction ERP.
"""
from decimal import Decimal
from django.db import models
from django.db.models import Sum, Q
from simple_history.models import HistoricalRecords

from apps.core.models import AuditMixin, Partner


class Project(AuditMixin, models.Model):
    """
    Construction project model.
    All financial documents can be linked to a project for reporting.
    """
    STATUS_CHOICES = [
        ('active', 'نشط'),
        ('completed', 'مكتمل'),
        ('on_hold', 'معلق'),
        ('cancelled', 'ملغي'),
    ]

    code = models.CharField('رمز المشروع', max_length=20, unique=True)
    name = models.CharField('اسم المشروع', max_length=255)
    customer = models.ForeignKey(
        Partner,
        on_delete=models.PROTECT,
        limit_choices_to={'type': 'customer'},
        related_name='projects',
        verbose_name='العميل',
    )
    status = models.CharField('الحالة', max_length=20, choices=STATUS_CHOICES, default='active')
    start_date = models.DateField('تاريخ البدء', null=True, blank=True)
    end_date = models.DateField('تاريخ الانتهاء', null=True, blank=True)
    budget = models.DecimalField(
        'الميزانية',
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    description = models.TextField('الوصف', blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'مشروع'
        verbose_name_plural = 'المشاريع'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.code} - {self.name}'

    def get_status_display_ar(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    @property
    def total_revenue(self):
        """Total posted invoice amount for this project."""
        from apps.invoicing.models import Invoice
        result = Invoice.objects.filter(
            project=self,
            status='posted'
        ).aggregate(total=Sum('amount'))
        return result['total'] or Decimal('0.00')

    @property
    def total_expenses(self):
        """Total posted expenses for this project."""
        from apps.expenses.models import Expense
        result = Expense.objects.filter(
            project=self,
            status='posted'
        ).aggregate(total=Sum('amount'))
        return result['total'] or Decimal('0.00')

    @property
    def total_bills(self):
        """Total posted bills for this project."""
        from apps.invoicing.models import Bill
        result = Bill.objects.filter(
            project=self,
            status='posted'
        ).aggregate(total=Sum('amount'))
        return result['total'] or Decimal('0.00')

    @property
    def gross_margin(self):
        """Revenue - Expenses - Bills."""
        return self.total_revenue - self.total_expenses - self.total_bills

    @property
    def total_receivables(self):
        """Outstanding AR for this project (invoices - payments received)."""
        from apps.invoicing.models import Invoice
        invoices = Invoice.objects.filter(
            project=self,
            status='posted'
        )
        total = Decimal('0.00')
        for inv in invoices:
            total += inv.amount_remaining
        return total

    @property
    def total_payables(self):
        """Outstanding AP for this project (bills - payments made)."""
        from apps.invoicing.models import Bill
        bills = Bill.objects.filter(
            project=self,
            status='posted'
        )
        total = Decimal('0.00')
        for bill in bills:
            total += bill.amount_remaining
        return total

    @property
    def open_advances(self):
        """Outstanding (unsettled) balance of posted advances for this project."""
        from apps.advances.models import CashAdvance
        total = Decimal('0.00')
        for adv in CashAdvance.objects.filter(project=self, status='posted'):
            total += adv.remaining
        return total
