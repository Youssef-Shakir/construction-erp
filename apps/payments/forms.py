"""
Forms for payments app.
"""
from django import forms
from .models import Payment, PaymentAllocation
from apps.core.models import Partner
from apps.core.forms import enable_quick_create
from apps.accounting.models import Account


class PaymentForm(forms.ModelForm):
    """Form for creating/editing payments."""

    class Meta:
        model = Payment
        fields = ['direction', 'partner', 'date', 'account', 'amount', 'reference', 'memo']
        widgets = {
            'direction': forms.Select(attrs={'class': 'form-select'}),
            'partner': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'account': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input money', 'step': '0.01', 'min': '0.01'}),
            'reference': forms.TextInput(attrs={'class': 'form-input'}),
            'memo': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        direction = kwargs.pop('direction', None)
        super().__init__(*args, **kwargs)

        # Cash/Bank accounts only
        self.fields['account'].queryset = Account.objects.filter(
            code__in=['1000', '1010'],  # Cash and Bank
            is_active=True
        )

        # Filter partners based on direction
        if direction == 'inbound' or (self.instance and self.instance.direction == 'inbound'):
            self.fields['partner'].queryset = Partner.objects.filter(
                type='customer',
                is_active=True
            )
        elif direction == 'outbound' or (self.instance and self.instance.direction == 'outbound'):
            self.fields['partner'].queryset = Partner.objects.filter(
                type='supplier',
                is_active=True
            )
        else:
            self.fields['partner'].queryset = Partner.objects.filter(is_active=True)
        partner_type = {'inbound': 'customer', 'outbound': 'supplier'}.get(
            direction or getattr(self.instance, 'direction', ''), '')
        enable_quick_create(self.fields['partner'], partner_type)


class PaymentAllocationForm(forms.Form):
    """Form for allocating payment to documents."""
    document_id = forms.IntegerField(widget=forms.HiddenInput())
    amount = forms.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-input money', 'step': '0.01'})
    )
