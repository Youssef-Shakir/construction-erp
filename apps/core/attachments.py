"""
Attachment services: validation, scanner/camera image handling, scan inbox.

Every path that stores a file (document tab upload, create-form upload,
scan inbox upload, `import_scans` folder import) goes through
`prepare_files()` + `store_attachments()` so the same rules apply everywhere:

- whitelist of extensions, checked against the file's real magic bytes
- size limit (settings.ATTACHMENT_MAX_UPLOAD_MB)
- phone photos: EXIF rotation applied, GPS/EXIF stripped, downscaled
- multi-page scanner TIFFs converted to one PDF (browsers can't show TIFF)
- several images can be merged into ONE PDF (multi-page scan with a phone)
- SHA-256 de-duplication per document
- files stored under <app>/<model>/<id>/<uuid>.<ext> (inbox/YYYY/MM/ when
  not yet linked to a document); the original filename is kept in the DB
"""
import hashlib
import os
import uuid
from dataclasses import dataclass, field
from io import BytesIO

from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

# Document types that can carry attachments.
# key -> (app_label.Model, number field, Arabic label, detail url name)
ATTACHABLE_DOCUMENTS = {
    'advance': ('advances.CashAdvance', 'advance_number', 'سلفة نقدية', 'advances:detail'),
    'advance_return': ('advances.AdvanceReturn', 'return_number', 'مردود سلفة', None),
    'expense': ('expenses.Expense', 'expense_number', 'مصروف', 'expenses:detail'),
    'expense_batch': ('expenses.ExpenseBatch', 'batch_number', 'مستند مصاريف', 'expenses:batch_detail'),
    'receipt': ('expenses.PaperReceipt', 'receipt_number', 'إيصال ورقي', None),
    'invoice': ('invoicing.Invoice', 'invoice_number', 'فاتورة عميل', 'invoicing:detail'),
    'bill': ('invoicing.Bill', 'bill_number', 'فاتورة مورد', 'bills:detail'),
    'payment': ('payments.Payment', 'payment_number', 'دفعة', 'payments:detail'),
}

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
TIFF_EXTENSIONS = {'.tif', '.tiff'}

# extension -> (canonical mime type, magic-byte checker)
_SIGNATURES = {
    '.pdf': ('application/pdf', lambda b: b.startswith(b'%PDF-')),
    '.jpg': ('image/jpeg', lambda b: b.startswith(b'\xff\xd8\xff')),
    '.jpeg': ('image/jpeg', lambda b: b.startswith(b'\xff\xd8\xff')),
    '.png': ('image/png', lambda b: b.startswith(b'\x89PNG\r\n\x1a\n')),
    '.webp': ('image/webp', lambda b: b[:4] == b'RIFF' and b[8:12] == b'WEBP'),
    '.tif': ('image/tiff', lambda b: b[:4] in (b'II*\x00', b'MM\x00*')),
    '.tiff': ('image/tiff', lambda b: b[:4] in (b'II*\x00', b'MM\x00*')),
    '.xlsx': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
              lambda b: b.startswith(b'PK\x03\x04')),
    '.docx': ('application/vnd.openxmlformats-officedocument.wordprocessingml.document',
              lambda b: b.startswith(b'PK\x03\x04')),
    '.xls': ('application/vnd.ms-excel', lambda b: b.startswith(b'\xd0\xcf\x11\xe0')),
    '.doc': ('application/msword', lambda b: b.startswith(b'\xd0\xcf\x11\xe0')),
    '.csv': ('text/csv', lambda b: b'\x00' not in b[:4096]),
}

ALLOWED_EXTENSIONS = sorted(_SIGNATURES)
ACCEPT_ATTR = ','.join(ALLOWED_EXTENSIONS)  # for <input accept="...">


class AttachmentError(Exception):
    """A file was rejected (type, size, unreadable...)."""


@dataclass
class PreparedFile:
    original_filename: str
    content: bytes
    mime_type: str
    sha256: str = field(init=False)

    def __post_init__(self):
        self.sha256 = hashlib.sha256(self.content).hexdigest()

    @property
    def size(self):
        return len(self.content)

    @property
    def extension(self):
        return os.path.splitext(self.original_filename)[1].lower()


# --------------------------------------------------------------------------
# Settings helpers
# --------------------------------------------------------------------------
def max_upload_bytes():
    return int(getattr(settings, 'ATTACHMENT_MAX_UPLOAD_MB', 25)) * 1024 * 1024


def _max_image_dim():
    return int(getattr(settings, 'ATTACHMENT_IMAGE_MAX_DIMENSION', 2800))


# --------------------------------------------------------------------------
# Validation + normalisation
# --------------------------------------------------------------------------
def _read(uploaded):
    if uploaded.size is not None and uploaded.size > max_upload_bytes():
        raise AttachmentError(
            f'الملف "{uploaded.name}" أكبر من الحد المسموح '
            f'({getattr(settings, "ATTACHMENT_MAX_UPLOAD_MB", 25)} ميجابايت)'
        )
    data = uploaded.read()
    if len(data) > max_upload_bytes():
        raise AttachmentError(f'الملف "{uploaded.name}" أكبر من الحد المسموح')
    if not data:
        raise AttachmentError(f'الملف "{uploaded.name}" فارغ')
    return data


def _safe_name(name):
    name = os.path.basename(name or 'file').strip().replace('\x00', '')
    return name[:200] or 'file'


def _open_image(data, name):
    try:
        img = Image.open(BytesIO(data))
        img.load()
        return img
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise AttachmentError(f'تعذّر قراءة الصورة "{name}"') from exc


def _to_rgb(img):
    img = ImageOps.exif_transpose(img)
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGBA')
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    if img.mode not in ('RGB', 'L'):
        return img.convert('RGB')
    return img


def _downscale(img):
    limit = _max_image_dim()
    if max(img.size) > limit:
        img = img.copy()
        img.thumbnail((limit, limit), Image.LANCZOS)
    return img


def _normalise_image(data, name):
    """
    Apply EXIF rotation, drop EXIF (GPS!) and downscale camera photos.
    Re-encodes JPEGs always; PNG/WebP only when too large.
    """
    img = _open_image(data, name)
    ext = os.path.splitext(name)[1].lower()
    too_big = max(img.size) > _max_image_dim()
    if ext not in ('.jpg', '.jpeg') and not too_big:
        return data, name
    img = _downscale(_to_rgb(img))
    out = BytesIO()
    if ext in ('.jpg', '.jpeg'):
        img.save(out, 'JPEG', quality=85, optimize=True)
    elif ext == '.png':
        img.save(out, 'PNG', optimize=True)
    else:
        img.save(out, 'WEBP', quality=85)
    return out.getvalue(), name


def images_to_pdf(images, name):
    """Merge PIL images (pages) into a single PDF."""
    pages = [_downscale(_to_rgb(im)).convert('RGB') for im in images]
    if not pages:
        raise AttachmentError('لا توجد صفحات لدمجها')
    out = BytesIO()
    pages[0].save(out, 'PDF', save_all=True, append_images=pages[1:], resolution=150.0)
    return PreparedFile(name, out.getvalue(), 'application/pdf')


def _tiff_to_pdf(data, name):
    img = _open_image(data, name)
    frames = [frame.copy() for frame in ImageSequence.Iterator(img)]
    base = os.path.splitext(name)[0]
    return images_to_pdf(frames, f'{base}.pdf')


def prepare_file(uploaded):
    """Validate one uploaded file and return a PreparedFile (raises AttachmentError)."""
    name = _safe_name(uploaded.name)
    ext = os.path.splitext(name)[1].lower()
    if ext not in _SIGNATURES:
        raise AttachmentError(
            f'نوع الملف "{name}" غير مسموح. الأنواع المسموحة: {", ".join(ALLOWED_EXTENSIONS)}'
        )
    data = _read(uploaded)
    mime, matches = _SIGNATURES[ext]
    if not matches(data[:16] if ext != '.csv' else data):
        raise AttachmentError(f'محتوى الملف "{name}" لا يطابق امتداده')

    if ext in TIFF_EXTENSIONS:
        return _tiff_to_pdf(data, name)
    if ext in IMAGE_EXTENSIONS:
        data, name = _normalise_image(data, name)
    return PreparedFile(name, data, mime)


def prepare_files(uploaded_files, combine_images=False, combined_name=None):
    """
    Validate a batch of uploads.

    combine_images=True merges every image in the batch (in upload order)
    into one PDF - used for multi-page documents photographed with a phone.

    Returns (prepared_files, error_messages). One bad file doesn't block
    the others.
    """
    prepared, errors, images = [], [], []
    for uploaded in uploaded_files:
        ext = os.path.splitext(uploaded.name or '')[1].lower()
        try:
            if combine_images and ext in IMAGE_EXTENSIONS:
                data = _read(uploaded)
                mime, matches = _SIGNATURES[ext]
                if not matches(data[:16]):
                    raise AttachmentError(f'محتوى الملف "{uploaded.name}" لا يطابق امتداده')
                images.append((_open_image(data, uploaded.name), _safe_name(uploaded.name)))
            else:
                prepared.append(prepare_file(uploaded))
        except AttachmentError as exc:
            errors.append(str(exc))

    if images:
        if len(images) == 1 and not combined_name:
            # A single photo: keep it as an image, no point wrapping in a PDF.
            out = BytesIO()
            img, original = images[0]
            _downscale(_to_rgb(img)).convert('RGB').save(out, 'JPEG', quality=85, optimize=True)
            jpg_name = os.path.splitext(original)[0] + '.jpg'
            prepared.append(PreparedFile(jpg_name, out.getvalue(), 'image/jpeg'))
        else:
            stamp = timezone.localtime().strftime('%Y%m%d-%H%M')
            name = combined_name or f'scan-{stamp}.pdf'
            if not name.lower().endswith('.pdf'):
                name += '.pdf'
            try:
                prepared.append(images_to_pdf([im for im, _ in images], _safe_name(name)))
            except AttachmentError as exc:
                errors.append(str(exc))
    return prepared, errors


# --------------------------------------------------------------------------
# Document registry
# --------------------------------------------------------------------------
def attachable_models():
    return {key: apps.get_model(label) for key, (label, *_rest) in ATTACHABLE_DOCUMENTS.items()}


def is_attachable(obj_or_model):
    model = obj_or_model if isinstance(obj_or_model, type) else type(obj_or_model)
    return model in attachable_models().values()


def attachable_content_type_ids():
    return {ContentType.objects.get_for_model(m).pk for m in attachable_models().values()}


def describe_document(obj):
    """(type label, number, detail url or None) for display."""
    from django.urls import reverse
    for key, model in attachable_models().items():
        if isinstance(obj, model):
            _label, number_field, ar_label, url_name = ATTACHABLE_DOCUMENTS[key]
            url = reverse(url_name, args=[obj.pk]) if url_name else None
            return ar_label, getattr(obj, number_field), url
    return '', str(obj), None


def find_document_by_number(number):
    """Look up a document by its number (INV-000012, BILL-000003, ...)."""
    number = (number or '').strip().upper()
    if not number:
        return None
    for key, model in attachable_models().items():
        number_field = ATTACHABLE_DOCUMENTS[key][1]
        obj = model.objects.filter(**{number_field: number}).first()
        if obj is not None:
            return obj
    return None


def document_is_locked(obj):
    """Posted/closed/cancelled documents: their evidence must not silently disappear."""
    status = getattr(obj, 'status', None)
    return status is not None and status != 'draft'


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
def storage_path(content_type, object_id, extension):
    """<app>/<model>/<id>/<uuid>.<ext>, or inbox/YYYY/MM/<uuid>.<ext>."""
    fname = f'{uuid.uuid4().hex}{extension}'
    if content_type is None or object_id is None:
        now = timezone.now()
        return os.path.join('inbox', f'{now:%Y}', f'{now:%m}', fname)
    return os.path.join(content_type.app_label, content_type.model, str(object_id), fname)


def store_attachments(prepared_files, *, target=None, user=None, source='upload', description=''):
    """
    Save prepared files, linked to `target` (a document) or to the scan
    inbox when target is None. Files identical (SHA-256) to one already on
    the same document / in the inbox are skipped.

    Returns (created_attachments, skipped_duplicate_names).
    """
    from .models import Attachment

    if target is not None and not is_attachable(target):
        raise AttachmentError('لا يمكن إرفاق ملفات بهذا النوع من المستندات')

    ct = ContentType.objects.get_for_model(target) if target is not None else None
    object_id = target.pk if target is not None else None

    created, skipped = [], []
    with transaction.atomic():
        for pf in prepared_files:
            existing = Attachment.objects.filter(
                sha256=pf.sha256, content_type=ct, object_id=object_id,
            )
            if existing.exists():
                skipped.append(pf.original_filename)
                continue
            att = Attachment(
                content_type=ct,
                object_id=object_id,
                original_filename=pf.original_filename,
                description=description[:255],
                uploaded_by=user,
                mime_type=pf.mime_type,
                file_size=pf.size,
                sha256=pf.sha256,
                source=source,
            )
            att.file.save(storage_path(ct, object_id, pf.extension), ContentFile(pf.content), save=False)
            att.save()
            created.append(att)
    return created, skipped


def assign_to_document(attachment, target, user=None):
    """Move a scan-inbox attachment onto a document (file is moved too)."""
    if attachment.content_type_id is not None:
        raise AttachmentError('هذا المرفق مرتبط بمستند بالفعل')
    if not is_attachable(target):
        raise AttachmentError('لا يمكن إرفاق ملفات بهذا النوع من المستندات')

    ct = ContentType.objects.get_for_model(target)
    old_name = attachment.file.name
    storage = attachment.file.storage
    ext = os.path.splitext(old_name)[1].lower()

    with transaction.atomic():
        with storage.open(old_name, 'rb') as fh:
            new_name = storage.save(storage_path(ct, target.pk, ext), fh)
        attachment.file.name = new_name
        attachment.content_type = ct
        attachment.object_id = target.pk
        attachment.assigned_by = user
        attachment.assigned_at = timezone.now()
        attachment.save()
        transaction.on_commit(lambda: storage.delete(old_name))
    return attachment


def attachments_for(obj):
    from .models import Attachment
    ct = ContentType.objects.get_for_model(obj)
    return Attachment.objects.filter(content_type=ct, object_id=obj.pk).select_related('uploaded_by')


def inbox_items():
    from .models import Attachment
    return Attachment.objects.filter(content_type__isnull=True).select_related('uploaded_by')


def attach_from_request(request, target, field='attachments', combine_field='combine_images'):
    """
    Used by document create forms: validate + store files posted in `field`
    and report problems through Django messages (the document itself is
    still saved - a bad attachment shouldn't lose the user's form data).
    """
    from django.contrib import messages

    files = request.FILES.getlist(field)
    if not files:
        return []
    source = 'camera' if request.POST.get('upload_source') == 'camera' else 'upload'
    prepared, errors = prepare_files(files, combine_images=bool(request.POST.get(combine_field)))
    created, skipped = store_attachments(prepared, target=target, user=request.user, source=source)
    for err in errors:
        messages.error(request, err)
    if skipped:
        messages.warning(request, 'ملفات مكررة لم تُرفع: ' + '، '.join(skipped))
    return created
