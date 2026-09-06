"""
Forms for invoicing app.
"""
from django import forms
from .models import Invoice, Bill
from apps.core.models import Partner
from apps.projects.models import Project
from apps.accounting.models import Account


class InvoiceForm(forms.ModelForm):
    """Form for creating/editing invoices."""

    class Meta:
        model = Invoice
        fields = ['project', 'customer', 'date', 'due_date', 'amount', 'description']
        widgets = {
            'project': forms.Select(attrs={'class': 'form-select'}),
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'due_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input money', 'step': '0.01', 'min': '0.01'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['project'].queryset = Project.objects.filter(status='active')
        self.fields['customer'].queryset = Partner.objects.filter(
            type='customer',
            is_active=True
        )


class BillForm(forms.ModelForm):
    """Form for creating/editing bills."""

    class Meta:
        model = Bill
        fields = ['project', 'supplier', 'account', 'date', 'due_date', 'vendor_reference', 'amount', 'description']
        widgets = {
            'project': forms.Select(attrs={'class': 'form-select'}),
            'supplier': forms.Select(attrs={'class': 'form-select'}),
            'account': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'due_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'vendor_reference': forms.TextInput(attrs={'class': 'form-input'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input money', 'step': '0.01', 'min': '0.01'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['project'].queryset = Project.objects.filter(status='active')
        self.fields['project'].required = False
        self.fields['supplier'].queryset = Partner.objects.filter(
            type='supplier',
            is_active=True
        )
        self.fields['account'].queryset = Account.objects.filter(
            account_type__code='expense',
            is_active=True
        ).order_by('code')
