"""
Forms for projects app.
"""
from django import forms
from django.db import models
from .models import Project
from apps.core.models import Partner
from apps.core.forms import enable_quick_create


def selectable_projects(form, field='project'):
    """
    Active projects, plus the project this form is about even if it is
    completed / on hold: the one it was opened from (?project=), the one the
    document already has (edit), or the one submitted. Without this a form
    opened from a completed project's page would silently lose the project.
    """
    keep = set()
    initial = form.initial.get(field)
    if initial:
        keep.add(getattr(initial, 'pk', initial))
    instance_pk = getattr(form.instance, f'{field}_id', None)
    if instance_pk:
        keep.add(instance_pk)
    submitted = form.data.get(form.add_prefix(field)) if form.is_bound else None
    if submitted and str(submitted).isdigit():
        keep.add(int(submitted))
    q = models.Q(status='active')
    if keep:
        q |= models.Q(pk__in=keep) & ~models.Q(status='cancelled')
    return Project.objects.filter(q).select_related('customer').order_by('code')


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
