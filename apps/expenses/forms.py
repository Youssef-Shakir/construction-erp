"""
Forms for expenses app.
"""
from django import forms
from .models import Expense, ExpenseBatch, PaperReceipt
from apps.core.models import Partner
from apps.core.forms import enable_quick_create
from apps.projects.models import Project
from apps.advances.models import CashAdvance
from apps.accounting.models import Account


class ExpenseForm(forms.ModelForm):
    """Form for creating/editing expenses."""

    class Meta:
        model = Expense
        fields = ['date', 'project', 'advance', 'account', 'partner', 'amount', 'description', 'receipt_number']
        widgets = {
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'project': forms.Select(attrs={'class': 'form-select'}),
            'advance': forms.Select(attrs={'class': 'form-select'}),
            'account': forms.Select(attrs={'class': 'form-select'}),
            'partner': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input money', 'step': '0.01', 'min': '0.01'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
            'receipt_number': forms.TextInput(attrs={'class': 'form-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['project'].queryset = Project.objects.filter(status='active')
        self.fields['project'].required = False

        self.fields['advance'].queryset = CashAdvance.objects.filter(
            status='posted'
        ).select_related('project', 'recipient')
        self.fields['advance'].required = False

        # Only expense accounts
        self.fields['account'].queryset = Account.objects.filter(
            account_type__code='expense',
            is_active=True
        ).order_by('code')

        # Paid to: any supplier, customer or employee - new ones can be added from the form
        self.fields['partner'].queryset = Partner.objects.filter(is_active=True)
        self.fields['partner'].required = False
        self.fields['partner'].label = 'الجهة المدفوع لها'
        enable_quick_create(self.fields['partner'], default='supplier')


class ExpenseLineForm(forms.ModelForm):
    """
    One row in a bulk expense entry sheet against a cash advance.
    A blank row (nothing filled in) is simply ignored by the formset.
    """

    class Meta:
        model = Expense
        fields = ['date', 'project', 'account', 'description', 'receipt_number', 'amount']
        widgets = {
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'project': forms.Select(attrs={'class': 'form-select'}),
            'account': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.TextInput(attrs={'class': 'form-input'}),
            'receipt_number': forms.TextInput(attrs={'class': 'form-input'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input money', 'step': '0.01', 'min': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['date'].required = False
        self.fields['project'].queryset = Project.objects.filter(status='active')
        self.fields['project'].required = False
        self.fields['account'].queryset = Account.objects.filter(
            account_type__code='expense',
            is_active=True
        ).order_by('code')
        self.fields['account'].required = False
        self.fields['description'].required = False
        self.fields['amount'].required = False


class ExpenseBatchHeaderForm(forms.ModelForm):
    """Header info for a bulk expense-lines document (مستند مصاريف)."""

    class Meta:
        model = ExpenseBatch
        fields = ['date', 'memo']
        widgets = {
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'memo': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'بيان عام للمستند (اختياري)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['memo'].required = False


# Starts with a single row; more rows are added dynamically in the browser
# (see advance_expense_lines.html) by cloning formset.empty_form and bumping
# TOTAL_FORMS - not by rendering a fixed batch of blank rows server-side.
ExpenseLineFormSet = forms.formset_factory(ExpenseLineForm, extra=1, can_delete=True)


class PaperReceiptForm(forms.ModelForm):
    """Form for creating paper receipts."""

    class Meta:
        model = PaperReceipt
        fields = ['vendor_name', 'date', 'amount', 'description', 'received_from', 'notes']
        widgets = {
            'vendor_name': forms.TextInput(attrs={'class': 'form-input'}),
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input money', 'step': '0.01', 'min': '0.01'}),
            'description': forms.TextInput(attrs={'class': 'form-input'}),
            'received_from': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['received_from'].queryset = Partner.objects.filter(
            type='employee',
            is_active=True
        )
        enable_quick_create(self.fields['received_from'], 'employee')
