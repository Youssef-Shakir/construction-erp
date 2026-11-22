"""
Forms for accounting app.
"""
from decimal import Decimal
from django import forms
from django.forms import inlineformset_factory

from .models import Account, AccountType, Journal, JournalEntry, JournalLine
from apps.core.models import Partner
from apps.projects.models import Project
from apps.projects.forms import selectable_projects


class AccountForm(forms.ModelForm):
    """Form for creating/editing accounts."""

    class Meta:
        model = Account
        fields = ['code', 'name', 'name_en', 'account_type', 'parent', 'is_control', 'is_active', 'description']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-input'}),
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            'name_en': forms.TextInput(attrs={'class': 'form-input'}),
            'account_type': forms.Select(attrs={'class': 'form-select'}),
            'parent': forms.Select(attrs={'class': 'form-select'}),
            'is_control': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
        }


class JournalForm(forms.ModelForm):
    """Form for creating/editing journals."""

    class Meta:
        model = Journal
        fields = ['code', 'name', 'type', 'default_debit_account', 'default_credit_account', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-input'}),
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'default_debit_account': forms.Select(attrs={'class': 'form-select'}),
            'default_credit_account': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }


class JournalEntryForm(forms.ModelForm):
    """Form for creating manual journal entries."""

    class Meta:
        model = JournalEntry
        fields = ['journal', 'date', 'memo']
        widgets = {
            'journal': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'memo': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['journal'].queryset = Journal.objects.filter(is_active=True)


class JournalLineForm(forms.ModelForm):
    """Form for journal entry lines."""

    class Meta:
        model = JournalLine
        fields = ['account', 'description', 'debit', 'credit', 'partner', 'project']
        widgets = {
            'account': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.TextInput(attrs={'class': 'form-input'}),
            'debit': forms.NumberInput(attrs={'class': 'form-input money', 'step': '0.01', 'min': '0'}),
            'credit': forms.NumberInput(attrs={'class': 'form-input money', 'step': '0.01', 'min': '0'}),
            'partner': forms.Select(attrs={'class': 'form-select'}),
            'project': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter accounts - non-control for regular users
        self.fields['account'].queryset = Account.objects.filter(
            is_active=True
        ).select_related('account_type').order_by('code')

        self.fields['partner'].queryset = Partner.objects.filter(is_active=True)
        self.fields['partner'].required = False

        self.fields['project'].queryset = selectable_projects(self)
        self.fields['project'].required = False

    def clean(self):
        cleaned_data = super().clean()
        debit = cleaned_data.get('debit') or Decimal('0.00')
        credit = cleaned_data.get('credit') or Decimal('0.00')

        if debit > 0 and credit > 0:
            raise forms.ValidationError('لا يمكن إدخال مبلغ مدين ودائن في نفس السطر')

        if debit == 0 and credit == 0:
            raise forms.ValidationError('يجب إدخال مبلغ مدين أو دائن')

        return cleaned_data


# Formset for journal entry lines
JournalLineFormSet = inlineformset_factory(
    JournalEntry,
    JournalLine,
    form=JournalLineForm,
    extra=4,
    can_delete=True,
    min_num=2,
    validate_min=True,
)


class LedgerFilterForm(forms.Form):
    """Form for filtering ledger view."""
    account = forms.ModelChoiceField(
        queryset=Account.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True,
        label='الحساب',
    )
    date_from = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
        required=False,
        label='من تاريخ',
    )
    date_to = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
        required=False,
        label='إلى تاريخ',
    )


class TrialBalanceFilterForm(forms.Form):
    """Form for trial balance date filter."""
    as_of_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
        required=False,
        label='حتى تاريخ',
    )
