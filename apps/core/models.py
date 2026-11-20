"""
Core models: CompanySettings, Partner, Attachment, and base mixins.
"""
import os
from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from simple_history.models import HistoricalRecords


class AuditMixin(models.Model):
    """
    Mixin for audit fields (created_by, updated_by, timestamps).
    Add to any model that needs audit tracking.
    """
    created_at = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)
    updated_at = models.DateTimeField('تاريخ التحديث', auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_created',
        verbose_name='أنشئ بواسطة',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_updated',
        verbose_name='حُدّث بواسطة',
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Get user from kwargs if provided by view
        user = kwargs.pop('user', None)
        if user:
            if not self.pk:
                self.created_by = user
            self.updated_by = user
        super().save(*args, **kwargs)


class DocumentSequence(models.Model):
    """Per-prefix counter used by core.sequences.next_document_number()."""
    key = models.CharField('البادئة', max_length=30, unique=True)
    next_value = models.PositiveBigIntegerField('القيمة التالية', default=1)

    class Meta:
        verbose_name = 'تسلسل المستندات'
        verbose_name_plural = 'تسلسلات المستندات'

    def __str__(self):
        return f'{self.key}: {self.next_value}'


class CompanySettings(models.Model):
    """
    Singleton model for company-wide settings.
    """
    name = models.CharField('اسم الشركة', max_length=255)
    currency = models.CharField('العملة', max_length=3, default='SAR')
    currency_symbol = models.CharField('رمز العملة', max_length=10, default='ر.س')
    fiscal_year_start = models.DateField('بداية السنة المالية', null=True, blank=True)
    address = models.TextField('العنوان', blank=True)
    phone = models.CharField('الهاتف', max_length=50, blank=True)
    email = models.EmailField('البريد الإلكتروني', blank=True)
    tax_number = models.CharField('الرقم الضريبي', max_length=50, blank=True)
    logo = models.ImageField('الشعار', upload_to='company/', blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'إعدادات الشركة'
        verbose_name_plural = 'إعدادات الشركة'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Ensure only one instance exists
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        """Get or create company settings."""
        obj, created = cls.objects.get_or_create(
            pk=1,
            defaults={'name': 'شركة المقاولات'}
        )
        return obj


class Partner(AuditMixin, models.Model):
    """
    Partner model - represents customers, suppliers, and employees.
    Used for AR/AP tracking and cash advance recipients.
    """
    PARTNER_TYPES = [
        ('customer', 'عميل'),
        ('supplier', 'مورد'),
        ('employee', 'موظف'),
    ]

    code = models.CharField('الرمز', max_length=20, unique=True)
    name = models.CharField('الاسم', max_length=255)
    type = models.CharField('النوع', max_length=20, choices=PARTNER_TYPES)
    email = models.EmailField('البريد الإلكتروني', blank=True)
    phone = models.CharField('الهاتف', max_length=50, blank=True)
    mobile = models.CharField('الجوال', max_length=50, blank=True)
    address = models.TextField('العنوان', blank=True)
    tax_number = models.CharField('الرقم الضريبي', max_length=50, blank=True)
    contact_person = models.CharField('الشخص المسؤول', max_length=255, blank=True)
    notes = models.TextField('ملاحظات', blank=True)
    is_active = models.BooleanField('نشط', default=True)

    # Link to User for employees who need system access
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='partner',
        verbose_name='حساب المستخدم',
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'شريك'
        verbose_name_plural = 'الشركاء'
        ordering = ['name']

    def __str__(self):
        return f'{self.code} - {self.name}'

    def get_type_display_ar(self):
        """Return type in Arabic."""
        return dict(self.PARTNER_TYPES).get(self.type, self.type)


def attachment_path(instance, filename):
    """
    Fallback upload path (core.attachments.store_attachments normally sets the
    name itself): <app>/<model>/<id>/<uuid>.<ext>, or inbox/ when unassigned.
    """
    from .attachments import storage_path
    return storage_path(instance.content_type, instance.object_id, os.path.splitext(filename)[1].lower())


class Attachment(models.Model):
    """
    File attached to a business document through a GenericForeignKey.

    content_type/object_id are NULL while the file sits in the scan inbox
    (uploaded or imported from a scanner folder, not yet linked to a document).
    Files are served only through core:attachment_download (login + permission).
    """
    SOURCE_CHOICES = [
        ('upload', 'رفع ملف'),
        ('camera', 'كاميرا'),
        ('scanner', 'ماسح ضوئي'),
    ]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    file = models.FileField('الملف', upload_to=attachment_path, max_length=255)
    original_filename = models.CharField('اسم الملف الأصلي', max_length=255)
    description = models.CharField('الوصف', max_length=255, blank=True)
    mime_type = models.CharField('نوع المحتوى', max_length=120, blank=True)
    file_size = models.PositiveBigIntegerField('الحجم', default=0)
    sha256 = models.CharField('البصمة', max_length=64, blank=True, db_index=True)
    source = models.CharField('المصدر', max_length=20, choices=SOURCE_CHOICES, default='upload')

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='رُفع بواسطة',
    )
    uploaded_at = models.DateTimeField('تاريخ الرفع', auto_now_add=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_attachments',
        verbose_name='رُبط بواسطة',
    )
    assigned_at = models.DateTimeField('تاريخ الربط', null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'مرفق'
        verbose_name_plural = 'المرفقات'
        ordering = ['-uploaded_at']
        indexes = [models.Index(fields=['content_type', 'object_id'])]

    def __str__(self):
        return self.original_filename

    def save(self, *args, **kwargs):
        if not self.original_filename and self.file:
            self.original_filename = os.path.basename(self.file.name)
        super().save(*args, **kwargs)

    @property
    def in_inbox(self):
        return self.content_type_id is None

    @property
    def file_extension(self):
        """Return the file extension."""
        _, ext = os.path.splitext(self.original_filename)
        return ext.lower()

    @property
    def is_image(self):
        """Check if attachment is an image."""
        return self.file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']

    @property
    def is_pdf(self):
        """Check if attachment is a PDF."""
        return self.file_extension == '.pdf'

    @property
    def can_display_inline(self):
        return self.is_image or self.is_pdf
