"""
Forms for expenses app.
"""
from django import forms
from .models import Expense, PaperReceipt
from apps.core.models import Partner
from apps.projects.models import Project
from apps.advances.models import CashAdvance
from apps.accounting.models import Account


class ExpenseForm(forms.ModelForm):
    """Form for creating/editing expenses."""

    class Meta:
        model = Expense
        fields = ['date', 'project', 'advance', 'account', 'partner', 'amount', 'description']
        widgets = {
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'project': forms.Select(attrs={'class': 'form-select'}),
            'advance': forms.Select(attrs={'class': 'form-select'}),
            'account': forms.Select(attrs={'class': 'form-select'}),
            'partner': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input money', 'step': '0.01', 'min': '0.01'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
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

        self.fields['partner'].queryset = Partner.objects.filter(
            type='supplier',
            is_active=True
        )
        self.fields['partner'].required = False


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
