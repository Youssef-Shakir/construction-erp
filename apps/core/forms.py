"""
Forms for core app.
"""
from django import forms
from .models import CompanySettings, Partner, Attachment


class CompanySettingsForm(forms.ModelForm):
    """Form for company settings."""

    class Meta:
        model = CompanySettings
        fields = [
            'name', 'currency', 'currency_symbol', 'fiscal_year_start',
            'address', 'phone', 'email', 'tax_number', 'logo'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            'currency': forms.TextInput(attrs={'class': 'form-input', 'maxlength': 3}),
            'currency_symbol': forms.TextInput(attrs={'class': 'form-input', 'maxlength': 10}),
            'fiscal_year_start': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'address': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'phone': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'tax_number': forms.TextInput(attrs={'class': 'form-input'}),
            'logo': forms.FileInput(attrs={'class': 'form-input'}),
        }


class PartnerForm(forms.ModelForm):
    """Form for creating/editing partners."""

    class Meta:
        model = Partner
        fields = [
            'code', 'name', 'type', 'email', 'phone', 'mobile',
            'address', 'tax_number', 'contact_person', 'notes', 'is_active'
        ]
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-input'}),
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'phone': forms.TextInput(attrs={'class': 'form-input'}),
            'mobile': forms.TextInput(attrs={'class': 'form-input'}),
            'address': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'tax_number': forms.TextInput(attrs={'class': 'form-input'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }


class AttachmentForm(forms.ModelForm):
    """Form for uploading attachments."""

    class Meta:
        model = Attachment
        fields = ['file', 'description']
        widgets = {
            'file': forms.FileInput(attrs={'class': 'form-input'}),
            'description': forms.TextInput(attrs={'class': 'form-input'}),
        }
