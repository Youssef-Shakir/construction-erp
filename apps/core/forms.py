"""
Forms for core app.
"""
from django import forms
from django.urls import reverse
from .models import CompanySettings, Partner, Attachment


def enable_quick_create(field, partner_type='', default=''):
    """
    Put "+" (new) and pencil (edit) buttons next to a partner <select>, so a
    customer/supplier/employee can be added or corrected without leaving the
    form (static/js/quick_create.js). partner_type '' lets the user choose.
    """
    url = reverse('core:partner_quick_create')
    if partner_type:
        url += f'?type={partner_type}'
    elif default:
        url += f'?default={default}'
    field.widget.attrs.update({
        'data-quick-create': url,
        'data-quick-edit': reverse('core:partner_quick_edit', args=[0]),
    })


class CompanySettingsForm(forms.ModelForm):
    """Form for company settings."""

    class Meta:
        model = CompanySettings
        fields = [
            'name', 'currency', 'currency_symbol', 'fiscal_year_start',
            'address', 'phone', 'email', 'tax_number', 'logo',
            'pdf_accent_color', 'pdf_header_note', 'invoice_terms', 'pdf_footer_text',
            'pdf_show_signatures',
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
            'pdf_accent_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-color'}),
            'pdf_header_note': forms.TextInput(attrs={'class': 'form-input'}),
            'invoice_terms': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'pdf_footer_text': forms.TextInput(attrs={'class': 'form-input'}),
            'pdf_show_signatures': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pdf_accent_color'].required = False   # empty -> default blue

    def clean_pdf_accent_color(self):
        import re
        value = self.cleaned_data['pdf_accent_color'] or '#1d4ed8'
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            raise forms.ValidationError('لون غير صالح')
        return value


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code'].required = False
        self.fields['code'].help_text = 'اتركه فارغاً ليُرقّم تلقائياً'


class PartnerQuickForm(forms.ModelForm):
    """Short partner form shown in the pop-up next to a partner field."""

    class Meta:
        model = Partner
        fields = ['name', 'type', 'phone', 'mobile', 'tax_number', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'autofocus': True}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'phone': forms.TextInput(attrs={'class': 'form-input'}),
            'mobile': forms.TextInput(attrs={'class': 'form-input'}),
            'tax_number': forms.TextInput(attrs={'class': 'form-input'}),
            'address': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
        }

    def __init__(self, *args, fixed_type='', **kwargs):
        super().__init__(*args, **kwargs)
        self.fixed_type = fixed_type
        if fixed_type:
            self.fields['type'].initial = fixed_type
            self.fields['type'].widget = forms.HiddenInput()

    def clean_type(self):
        return self.fixed_type or self.cleaned_data['type']


class AttachmentForm(forms.ModelForm):
    """Form for uploading attachments."""

    class Meta:
        model = Attachment
        fields = ['file', 'description']
        widgets = {
            'file': forms.FileInput(attrs={'class': 'form-input'}),
            'description': forms.TextInput(attrs={'class': 'form-input'}),
        }
