"""
Compress attachments that were stored before the compressor existed (or with
a lighter setting). Works with local disk and S3/MinIO storage alike.

    python manage.py compress_attachments --dry-run
    python manage.py compress_attachments --min-kb 500
"""
import os

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.attachments import (
    AttachmentError, _normalise_image, compress_pdf, storage_path,
)
from apps.core.models import Attachment


class Command(BaseCommand):
    help = 'Re-compress stored PDF/JPEG attachments, keeping a copy only when it is smaller.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--min-kb', type=int, default=300, help='Skip files smaller than this')

    def handle(self, *args, **opts):
        saved_total, done = 0, 0
        candidates = Attachment.objects.filter(
            file_size__gte=opts['min_kb'] * 1024,
            mime_type__in=['application/pdf', 'image/jpeg'],
        ).order_by('pk')

        for att in candidates.iterator():
            storage = att.file.storage
            try:
                with storage.open(att.file.name, 'rb') as fh:
                    data = fh.read()
            except Exception as exc:  # missing object, network error...
                self.stderr.write(f'  #{att.pk} {att.original_filename}: cannot read ({exc})')
                continue

            try:
                if att.mime_type == 'application/pdf':
                    smaller = compress_pdf(data)
                else:
                    smaller, _ = _normalise_image(data, att.original_filename)
            except AttachmentError:
                smaller = None
            if not smaller or len(smaller) >= len(data) * 0.9:
                continue

            saved = len(data) - len(smaller)
            self.stdout.write(f'  #{att.pk} {att.original_filename}: {len(data)} -> {len(smaller)} bytes')
            saved_total += saved
            done += 1
            if opts['dry_run']:
                continue

            old_name = att.file.name
            ext = os.path.splitext(old_name)[1].lower()
            with transaction.atomic():
                att.file.save(storage_path(att.content_type, att.object_id, ext), ContentFile(smaller), save=False)
                att.original_size = att.original_size or len(data)
                att.file_size = len(smaller)
                att.save(update_fields=['file', 'file_size', 'original_size'])
                transaction.on_commit(lambda name=old_name: storage.delete(name))

        verb = 'would save' if opts['dry_run'] else 'saved'
        self.stdout.write(self.style.SUCCESS(f'{done} files, {verb} {saved_total / 1024 / 1024:.1f} MB'))
