"""
Forms for projects app.
"""
from django import forms
from .models import Project
from apps.core.models import Partner
from apps.core.forms import enable_quick_create


class ProjectForm(forms.ModelForm):
    """Form for creating/editing projects."""

    class Meta:
        model = Project
        fields = [
            'code', 'name', 'customer', 'status',
            'start_date', 'end_date', 'budget', 'description'
        ]
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-input'}),
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'start_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'budget': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show active customers
        self.fields['customer'].queryset = Partner.objects.filter(
            type='customer',
            is_active=True
        ).order_by('name')
        enable_quick_create(self.fields['customer'], 'customer')
