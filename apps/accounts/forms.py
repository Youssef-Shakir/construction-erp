"""
Forms for accounts app.
"""
from django import forms
from .models import User


ROLE_CHOICES = [
    ('', '-- اختر الصلاحية --'),
    ('BusinessManager', 'مدير الأعمال'),
    ('Accountant', 'محاسب'),
    ('DataEntry', 'مدخل بيانات'),
]


class LoginForm(forms.Form):
    """Login form."""
    email = forms.EmailField(
        label='البريد الإلكتروني',
        widget=forms.EmailInput(attrs={
            'class': 'form-input',
            'placeholder': 'example@company.com',
            'autofocus': True,
        })
    )
    password = forms.CharField(
        label='كلمة المرور',
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': '••••••••',
        })
    )


class UserForm(forms.ModelForm):
    """Form for creating a new user."""
    password = forms.CharField(
        label='كلمة المرور',
        widget=forms.PasswordInput(attrs={'class': 'form-input'}),
        min_length=8,
    )
    password_confirm = forms.CharField(
        label='تأكيد كلمة المرور',
        widget=forms.PasswordInput(attrs={'class': 'form-input'}),
    )
    role = forms.ChoiceField(
        label='الصلاحية',
        choices=ROLE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True,
    )

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'is_active']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError('كلمتا المرور غير متطابقتين')

        return cleaned_data


class UserEditForm(forms.ModelForm):
    """Form for editing an existing user (no password)."""
    role = forms.ChoiceField(
        label='الصلاحية',
        choices=ROLE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True,
    )

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'is_active']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }


class PasswordChangeForm(forms.Form):
    """Form for changing password."""
    password = forms.CharField(
        label='كلمة المرور الجديدة',
        widget=forms.PasswordInput(attrs={'class': 'form-input'}),
        min_length=8,
    )
    password_confirm = forms.CharField(
        label='تأكيد كلمة المرور',
        widget=forms.PasswordInput(attrs={'class': 'form-input'}),
    )

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError('كلمتا المرور غير متطابقتين')

        return cleaned_data
