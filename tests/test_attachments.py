"""
Attachments, scanner/camera intake and the scan inbox.

Covers core.attachments (validation, image normalisation, PDF merge,
dedupe, inbox assignment), the core attachment views (permissions,
protected download) and the import_scans management command.
"""
import os
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from PIL import Image

from apps.core.attachments import (
    AttachmentError, assign_to_document, attachments_for, inbox_items,
    prepare_file, prepare_files, store_attachments,
)
from apps.core.models import Attachment
from apps.invoicing.models import Invoice

from tests.test_journal_rules import (  # noqa: F401
    account_types, accounts, journals, customer, supplier, employee, project,
)

PDF_BYTES = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


@pytest.fixture(autouse=True)
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / 'media'
    settings.ATTACHMENT_X_ACCEL_PREFIX = ''
    return settings.MEDIA_ROOT


def _jpeg(size=(400, 300), color=(200, 30, 30), exif_orientation=None):
    img = Image.new('RGB', size, color)
    out = BytesIO()
    kwargs = {}
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        exif[0x8825] = {2: (1.0, 2.0, 3.0)}  # GPS IFD - must be stripped
        kwargs['exif'] = exif.tobytes()
    img.save(out, 'JPEG', **kwargs)
    return out.getvalue()


def _upload(name, content, content_type='application/octet-stream'):
    return SimpleUploadedFile(name, content, content_type=content_type)


@pytest.fixture
def invoice(accounts, journals, customer, project):
    return Invoice.objects.create(
        project=project, customer=customer, date=date(2026, 1, 1),
        due_date=date(2026, 2, 1), description='Progress bill', amount=Decimal('1000'),
    )


def _user(django_user_model, email, group=None, superuser=False):
    if superuser:
        return django_user_model.objects.create_superuser(email=email, password='x', first_name='A', last_name='B')
    user = django_user_model.objects.create_user(email=email, password='x', first_name='A', last_name='B')
    if group:
        user.groups.add(Group.objects.get_or_create(name=group)[0])
    return user


# --------------------------------------------------------------------------
# Validation / processing
# --------------------------------------------------------------------------
class TestPrepare:
    def test_pdf_accepted(self):
        pf = prepare_file(_upload('scan.pdf', PDF_BYTES))
        assert pf.mime_type == 'application/pdf'
        assert len(pf.sha256) == 64

    def test_disallowed_extension_rejected(self):
        with pytest.raises(AttachmentError):
            prepare_file(_upload('evil.exe', b'MZ\x90\x00'))

    def test_html_rejected(self):
        with pytest.raises(AttachmentError):
            prepare_file(_upload('page.html', b'<script>alert(1)</script>'))

    def test_spoofed_extension_rejected(self):
        with pytest.raises(AttachmentError):
            prepare_file(_upload('invoice.pdf', b'<html>not a pdf</html>'))

    def test_size_limit(self, settings):
        settings.ATTACHMENT_MAX_UPLOAD_MB = 1
        with pytest.raises(AttachmentError):
            prepare_file(_upload('big.pdf', PDF_BYTES + b'0' * (1024 * 1024 + 1)))

    def test_camera_photo_rotated_downscaled_and_exif_stripped(self, settings):
        settings.ATTACHMENT_IMAGE_MAX_DIMENSION = 200
        pf = prepare_file(_upload('IMG_0001.jpg', _jpeg((400, 300), exif_orientation=6)))
        img = Image.open(BytesIO(pf.content))
        # orientation 6 = rotate 90deg -> portrait, then capped at 200px
        assert img.size == (150, 200)
        assert not img.getexif()

    def test_multipage_tiff_becomes_pdf(self):
        pages = [Image.new('RGB', (100, 140), c) for c in ('white', 'gray', 'black')]
        out = BytesIO()
        pages[0].save(out, 'TIFF', save_all=True, append_images=pages[1:])
        pf = prepare_file(_upload('scanner_0001.tif', out.getvalue()))
        assert pf.original_filename == 'scanner_0001.pdf'
        assert pf.content.startswith(b'%PDF')
        assert pf.content.count(b'/Type /Page\n') + pf.content.count(b'/Type /Page ') >= 3 or b'/Count 3' in pf.content

    def test_combine_photos_into_one_pdf(self):
        files = [_upload(f'p{i}.jpg', _jpeg()) for i in range(3)] + [_upload('other.pdf', PDF_BYTES)]
        prepared, errors = prepare_files(files, combine_images=True, combined_name='contract')
        assert errors == []
        names = sorted(p.original_filename for p in prepared)
        assert names == ['contract.pdf', 'other.pdf']
        merged = next(p for p in prepared if p.original_filename == 'contract.pdf')
        assert b'/Count 3' in merged.content

    def test_one_bad_file_does_not_block_others(self):
        prepared, errors = prepare_files([_upload('ok.pdf', PDF_BYTES), _upload('bad.exe', b'MZ')])
        assert len(prepared) == 1 and len(errors) == 1


# --------------------------------------------------------------------------
# Storage, dedupe, inbox
# --------------------------------------------------------------------------
class TestStorage:
    def test_store_on_document_with_uuid_path(self, invoice, media_tmp):
        created, skipped = store_attachments([prepare_file(_upload('../../etc/passwd.pdf', PDF_BYTES))], target=invoice)
        att = created[0]
        assert att.original_filename == 'passwd.pdf'
        assert att.file.name.startswith('invoicing/invoice/%d/' % invoice.pk)
        assert '..' not in att.file.name
        assert default_storage.exists(att.file.name)
        assert att.file_size == len(PDF_BYTES)

    def test_duplicate_on_same_document_skipped(self, invoice):
        pf = prepare_file(_upload('a.pdf', PDF_BYTES))
        store_attachments([pf], target=invoice)
        created, skipped = store_attachments([prepare_file(_upload('copy.pdf', PDF_BYTES))], target=invoice)
        assert created == [] and skipped == ['copy.pdf']

    def test_inbox_then_assign_moves_file(self, invoice, django_capture_on_commit_callbacks):
        created, _ = store_attachments([prepare_file(_upload('scan.pdf', PDF_BYTES))], target=None, source='scanner')
        item = created[0]
        old_name = item.file.name
        assert item.in_inbox and item.file.name.startswith('inbox/')
        assert list(inbox_items()) == [item]

        with django_capture_on_commit_callbacks(execute=True):
            assign_to_document(item, invoice)
        item.refresh_from_db()
        assert item.content_object == invoice
        assert item.file.name.startswith('invoicing/invoice/')
        assert default_storage.exists(item.file.name)
        assert not default_storage.exists(old_name)
        assert list(attachments_for(invoice)) == [item]

    def test_non_document_target_rejected(self, customer):
        # Partners are not attachable document types
        with pytest.raises(AttachmentError):
            store_attachments([prepare_file(_upload('a.pdf', PDF_BYTES))], target=customer)


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------
class TestViews:
    def test_upload_via_htmx_endpoint(self, client, invoice, django_user_model):
        client.force_login(_user(django_user_model, 'acc@example.com', 'Accountant'))
        ct = ContentType.objects.get_for_model(Invoice)
        resp = client.post(reverse('core:attachment_upload'), {
            'content_type_id': ct.pk, 'object_id': invoice.pk,
            'file': [_upload('a.pdf', PDF_BYTES), _upload('b.exe', b'MZ')],
        })
        assert resp.status_code == 200
        assert attachments_for(invoice).count() == 1
        assert 'غير مسموح' in resp.content.decode()

    def test_upload_to_non_document_type_404(self, client, invoice, django_user_model):
        user = _user(django_user_model, 'acc@example.com', 'Accountant')
        client.force_login(user)
        ct = ContentType.objects.get_for_model(django_user_model)
        resp = client.post(reverse('core:attachment_upload'), {
            'content_type_id': ct.pk, 'object_id': user.pk, 'file': _upload('a.pdf', PDF_BYTES),
        })
        assert resp.status_code == 404

    def test_download_requires_login_and_sets_headers(self, client, invoice, django_user_model):
        att = store_attachments([prepare_file(_upload('a b.pdf', PDF_BYTES))], target=invoice)[0][0]
        url = reverse('core:attachment_download', args=[att.pk])
        assert client.get(url).status_code == 302  # to login
        client.force_login(_user(django_user_model, 'de@example.com', 'DataEntry'))
        resp = client.get(url)
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'application/pdf'
        assert resp['X-Content-Type-Options'] == 'nosniff'
        assert resp['Content-Disposition'].startswith('inline')
        assert b''.join(resp.streaming_content) == PDF_BYTES

    def test_x_accel_redirect(self, client, invoice, django_user_model, settings):
        settings.ATTACHMENT_X_ACCEL_PREFIX = '/protected-media/'
        att = store_attachments([prepare_file(_upload('a.pdf', PDF_BYTES))], target=invoice)[0][0]
        client.force_login(_user(django_user_model, 'de@example.com', 'DataEntry'))
        resp = client.get(reverse('core:attachment_download', args=[att.pk]))
        assert resp['X-Accel-Redirect'] == '/protected-media/' + att.file.name

    def test_attachment_of_posted_document_only_manager_can_delete(self, client, invoice, django_user_model):
        uploader = _user(django_user_model, 'de@example.com', 'DataEntry')
        att = store_attachments([prepare_file(_upload('a.pdf', PDF_BYTES))], target=invoice, user=uploader)[0][0]
        invoice.post()

        client.force_login(uploader)
        resp = client.post(reverse('core:attachment_delete', args=[att.pk]), HTTP_HX_REQUEST='true')
        assert resp.status_code == 403
        assert Attachment.objects.filter(pk=att.pk).exists()

        client.force_login(_user(django_user_model, 'boss@example.com', superuser=True))
        resp = client.post(reverse('core:attachment_delete', args=[att.pk]), HTTP_HX_REQUEST='true')
        assert resp.status_code == 200
        assert not Attachment.objects.filter(pk=att.pk).exists()

    def test_other_user_cannot_delete_draft_attachment(self, client, invoice, django_user_model):
        uploader = _user(django_user_model, 'de1@example.com', 'DataEntry')
        att = store_attachments([prepare_file(_upload('a.pdf', PDF_BYTES))], target=invoice, user=uploader)[0][0]
        client.force_login(_user(django_user_model, 'de2@example.com', 'DataEntry'))
        resp = client.post(reverse('core:attachment_delete', args=[att.pk]), HTTP_HX_REQUEST='true')
        assert resp.status_code == 403

    def test_inbox_upload_and_assign_by_number(self, client, invoice, django_user_model):
        client.force_login(_user(django_user_model, 'acc@example.com', 'Accountant'))
        resp = client.post(reverse('core:scan_inbox'), {
            'file': [_upload('p1.jpg', _jpeg()), _upload('p2.jpg', _jpeg(color=(1, 2, 3)))],
            'combine_images': '1', 'upload_source': 'camera',
        })
        assert resp.status_code == 302
        item = inbox_items().get()
        assert item.original_filename.endswith('.pdf') and item.source == 'camera'

        resp = client.post(reverse('core:scan_inbox_assign', args=[item.pk]), {
            'document_number': invoice.invoice_number.lower(), 'next': 'document',
        })
        assert resp.status_code == 302
        assert resp['Location'] == reverse('invoicing:detail', args=[invoice.pk])
        item.refresh_from_db()
        assert item.content_object == invoice

    def test_data_entry_cannot_assign_inbox(self, client, invoice, django_user_model):
        item = store_attachments([prepare_file(_upload('a.pdf', PDF_BYTES))], target=None)[0][0]
        client.force_login(_user(django_user_model, 'de@example.com', 'DataEntry'))
        client.post(reverse('core:scan_inbox_assign', args=[item.pk]), {'document_number': invoice.invoice_number})
        item.refresh_from_db()
        assert item.in_inbox

    def test_document_detail_renders_attachment_tab(self, client, invoice, django_user_model):
        store_attachments([prepare_file(_upload('a.pdf', PDF_BYTES))], target=None)
        client.force_login(_user(django_user_model, 'acc@example.com', 'Accountant'))
        resp = client.get(reverse('invoicing:detail', args=[invoice.pk]))
        html = resp.content.decode()
        assert resp.status_code == 200
        assert 'capture="environment"' in html
        assert reverse('core:attachment_from_inbox') in html


# --------------------------------------------------------------------------
# Scanner folder import
# --------------------------------------------------------------------------
class TestImportScans:
    def test_import_folder(self, tmp_path, invoice):
        drop = tmp_path / 'scans'
        drop.mkdir()
        (drop / f'{invoice.invoice_number}_signed.pdf').write_bytes(PDF_BYTES)
        (drop / 'unknown_doc.pdf').write_bytes(PDF_BYTES + b'x')
        (drop / 'virus.exe').write_bytes(b'MZ')

        call_command('import_scans', dir=str(drop), min_age=0)

        assert attachments_for(invoice).count() == 1
        assert attachments_for(invoice).get().source == 'scanner'
        assert inbox_items().count() == 1
        assert (drop / 'rejected' / 'virus.exe').exists()
        assert (drop / 'rejected' / 'virus.exe.error.txt').exists()
        processed = list((drop / 'processed').rglob('*.pdf'))
        assert len(processed) == 2
        assert not any(p.is_file() for p in drop.iterdir())


# --------------------------------------------------------------------------
# Compressor
# --------------------------------------------------------------------------
def _scanned_pdf(pages=2):
    """A 'scanned' PDF: big noisy full-page photos at high resolution (like a 300 dpi scan)."""
    import random
    rnd = random.Random(7)
    imgs = []
    for _ in range(pages):
        img = Image.new('RGB', (2480, 3508), 'white')
        px = img.load()
        for _ in range(60000):
            px[rnd.randrange(2480), rnd.randrange(3508)] = (rnd.randrange(256),) * 3
        imgs.append(img)
    out = BytesIO()
    imgs[0].save(out, 'PDF', save_all=True, append_images=imgs[1:], resolution=300.0, quality=95)
    return out.getvalue()


class TestCompressor:
    def test_large_scan_is_compressed_and_dedupes_on_original(self, invoice, settings):
        import shutil
        if not shutil.which('gs'):
            pytest.skip('Ghostscript not installed (it is in the Docker image)')
        settings.ATTACHMENT_PDF_COMPRESSION = 'ebook'
        settings.ATTACHMENT_PDF_COMPRESS_MIN_KB = 100
        raw = _scanned_pdf()
        pf = prepare_file(_upload('mfp-scan.pdf', raw))
        assert pf.content.startswith(b'%PDF-')
        assert pf.size < len(raw) * 0.9, (pf.size, len(raw))
        assert pf.original_size == len(raw)

        att = store_attachments([pf], target=invoice)[0][0]
        assert att.was_compressed and att.original_size == len(raw)
        # The same scan uploaded again is recognised although gs output differs per run
        created, skipped = store_attachments([prepare_file(_upload('again.pdf', raw))], target=invoice)
        assert created == [] and skipped == ['again.pdf']

    def test_compression_off_or_small_files_untouched(self, settings):
        settings.ATTACHMENT_PDF_COMPRESSION = 'off'
        pf = prepare_file(_upload('a.pdf', PDF_BYTES))
        assert pf.content == PDF_BYTES and not pf.original_size > pf.size

    def test_compress_attachments_command_dry_run(self, invoice):
        from io import StringIO
        store_attachments([prepare_file(_upload('a.pdf', PDF_BYTES))], target=invoice)
        out = StringIO()
        call_command('compress_attachments', dry_run=True, min_kb=0, stdout=out)
        assert 'files' in out.getvalue()
