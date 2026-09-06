"""
Custom User model for Construction ERP.
"""
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from simple_history.models import HistoricalRecords


class UserManager(BaseUserManager):
    """Custom user manager using email as unique identifier."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('البريد الإلكتروني مطلوب')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model using email as the unique identifier.
    """
    email = models.EmailField('البريد الإلكتروني', unique=True)
    first_name = models.CharField('الاسم الأول', max_length=150)
    last_name = models.CharField('اسم العائلة', max_length=150)
    is_staff = models.BooleanField('موظف', default=False)
    is_active = models.BooleanField('نشط', default=True)
    date_joined = models.DateTimeField('تاريخ الانضمام', auto_now_add=True)

    # Audit
    history = HistoricalRecords()

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    class Meta:
        verbose_name = 'مستخدم'
        verbose_name_plural = 'المستخدمين'
        ordering = ['first_name', 'last_name']

    def __str__(self):
        return self.get_full_name() or self.email

    def get_full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    def get_short_name(self):
        return self.first_name

    def get_role_display(self):
        """Return the user's role as Arabic text."""
        if self.is_superuser:
            return 'مدير النظام'
        groups = self.groups.values_list('name', flat=True)
        if 'BusinessManager' in groups:
            return 'مدير الأعمال'
        if 'Accountant' in groups:
            return 'محاسب'
        if 'DataEntry' in groups:
            return 'مدخل بيانات'
        return 'بدون صلاحية'
