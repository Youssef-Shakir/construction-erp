"""
Forms for advances app.
"""
from django import forms
from .models import CashAdvance, AdvanceReturn
from apps.core.models import Partner
from apps.projects.models import Project


class CashAdvanceForm(forms.ModelForm):
    """Form for creating/editing cash advances."""

    class Meta:
        model = CashAdvance
        fields = ['project', 'recipient', 'date', 'amount', 'purpose']
        widgets = {
            'project': forms.Select(attrs={'class': 'form-select'}),
            'recipient': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input money', 'step': '0.01', 'min': '0.01'}),
            'purpose': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['project'].queryset = Project.objects.filter(status='active')
        self.fields['recipient'].queryset = Partner.objects.filter(
            type='employee',
            is_active=True
        )


class AdvanceReturnForm(forms.ModelForm):
    """Form for creating advance returns."""

    class Meta:
        model = AdvanceReturn
        fields = ['advance', 'date', 'amount', 'notes']
        widgets = {
            'advance': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input money', 'step': '0.01', 'min': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show posted advances with remaining balance
        self.fields['advance'].queryset = CashAdvance.objects.filter(
            status='posted'
        ).select_related('project', 'recipient')
