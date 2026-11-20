"""
Import files dropped by office scanners into the scan inbox.

Typical setup: the multifunction printer's "Scan to folder" (SMB/FTP)
writes PDFs into SCAN_INBOX_DIR. Run this command from cron / a systemd
timer, or keep it running with --watch:

    python manage.py import_scans                 # one pass over SCAN_INBOX_DIR
    python manage.py import_scans --watch         # poll every 15 s
    python manage.py import_scans --dir /srv/scans --user accountant@example.com

Each file is validated exactly like a browser upload. If its name starts
with a document number (e.g. "BILL-000012.pdf", "INV-000003_contract.pdf")
it is attached straight to that document; otherwise it waits in the scan
inbox for an accountant to link it.

Processed files are moved to <dir>/processed/YYYY-MM-DD/, rejected ones to
<dir>/rejected/ with a .error.txt explaining why.
"""
import re
import shutil
import time
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.attachments import (
    AttachmentError, find_document_by_number, prepare_file, store_attachments,
)

DOC_NUMBER_RE = re.compile(r'^([A-Za-z]+(?:-[A-Za-z]+)?-\d{6})')


class Command(BaseCommand):
    help = 'Import scanned files from the scanner drop folder into the scan inbox.'

    def add_arguments(self, parser):
        parser.add_argument('--dir', help='Folder to import from (default: settings.SCAN_INBOX_DIR)')
        parser.add_argument('--user', help='Email of the user recorded as uploader')
        parser.add_argument('--watch', action='store_true', help='Keep running and poll the folder')
        parser.add_argument('--interval', type=int, default=15, help='Seconds between polls with --watch')
        parser.add_argument(
            '--min-age', type=int, default=10,
            help='Skip files modified in the last N seconds (scanner may still be writing)',
        )

    def handle(self, *args, **opts):
        folder = opts['dir'] or getattr(settings, 'SCAN_INBOX_DIR', '')
        if not folder:
            raise CommandError('Set SCAN_INBOX_DIR in the environment or pass --dir')
        folder = Path(folder)
        if not folder.is_dir():
            raise CommandError(f'Folder does not exist: {folder}')

        user = None
        if opts['user']:
            user = get_user_model().objects.filter(email=opts['user']).first()
            if user is None:
                raise CommandError(f'No user with email {opts["user"]}')

        while True:
            counts = self.import_once(folder, user, opts['min_age'])
            if any(counts.values()):
                self.stdout.write(
                    f'{timezone.localtime():%Y-%m-%d %H:%M:%S} '
                    f'inbox={counts["inbox"]} attached={counts["attached"]} '
                    f'duplicate={counts["duplicate"]} rejected={counts["rejected"]}'
                )
            if not opts['watch']:
                break
            time.sleep(max(1, opts['interval']))

    def import_once(self, folder, user, min_age):
        counts = {'inbox': 0, 'attached': 0, 'duplicate': 0, 'rejected': 0}
        now = time.time()
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.name.startswith('.') or path.name.endswith('.error.txt'):
                continue
            if now - path.stat().st_mtime < min_age:
                continue
            try:
                outcome = self.import_file(path, user)
            except AttachmentError as exc:
                self._reject(folder, path, str(exc))
                counts['rejected'] += 1
                continue
            counts[outcome] += 1
            self._archive(folder, path)
        return counts

    def import_file(self, path, user):
        with path.open('rb') as fh:
            prepared = prepare_file(File(fh, name=path.name))

        target = None
        match = DOC_NUMBER_RE.match(path.stem)
        if match:
            target = find_document_by_number(match.group(1))

        created, skipped = store_attachments([prepared], target=target, user=user, source='scanner')
        if skipped:
            return 'duplicate'
        label = f'-> {target}' if target else '-> inbox'
        self.stdout.write(f'  {path.name} {label}')
        return 'attached' if target else 'inbox'

    def _archive(self, folder, path):
        dest = folder / 'processed' / timezone.localdate().isoformat()
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(self._unique(dest / path.name)))

    def _reject(self, folder, path, reason):
        dest = folder / 'rejected'
        dest.mkdir(parents=True, exist_ok=True)
        target = self._unique(dest / path.name)
        shutil.move(str(path), str(target))
        target.with_name(target.name + '.error.txt').write_text(reason, encoding='utf-8')
        self.stderr.write(f'  rejected {path.name}: {reason}')

    @staticmethod
    def _unique(path):
        candidate, n = path, 1
        while candidate.exists():
            candidate = path.with_name(f'{path.stem}-{n}{path.suffix}')
            n += 1
        return candidate
