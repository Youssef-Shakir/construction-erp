# Deployment & scanner setup

Target: one Linux server (Ubuntu 24.04), PostgreSQL 16, gunicorn behind nginx, HTTPS.

## Local development

```bash
python3.12 -m venv venv && venv/bin/pip install -r requirements.txt
npm install && npm run watch:css            # Tailwind
export DJANGO_SETTINGS_MODULE=config.dev_settings
venv/bin/python manage.py migrate
venv/bin/python manage.py seed_demo         # demo chart of accounts, users, documents
venv/bin/python manage.py runserver
venv/bin/python -m pytest                   # tests (SQLite, config.test_settings)
```

Try the scanner flow locally: `mkdir scans`, drop a PDF in it, run
`venv/bin/python manage.py import_scans --dir scans --min-age 0`, open **صندوق المسح**.

## 1. Application

```bash
sudo useradd --system --home /srv/construction-erp erp
cd /srv/construction-erp && git clone <repo> app && cd app
python3.12 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env            # fill in SECRET_KEY, DB_*, ALLOWED_HOSTS, ...
npm ci && npm run build          # Tailwind -> static/css/output.css
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
venv/bin/python manage.py check --deploy
venv/bin/python manage.py createsuperuser
```

`seed_demo` is for demos. For a real company either create the chart of accounts and
journals yourself (the posting rules expect account codes 1000 cash, 1010 bank,
1100 AR, 1200 advances, 2000 AP, 4000 revenue and journals CASH, SALE, PURCH, GEN),
or run `seed_demo` on an empty database and delete the demo users and documents.

### gunicorn (`/etc/systemd/system/erp.service`)

```ini
[Service]
User=erp
WorkingDirectory=/srv/construction-erp/app
EnvironmentFile=/srv/construction-erp/app/.env
ExecStart=/srv/construction-erp/app/venv/bin/gunicorn config.wsgi:application \
    --bind 127.0.0.1:8000 --workers 3 --timeout 60
Restart=always
[Install]
WantedBy=multi-user.target
```

### nginx

Attachments are financial evidence: **never expose MEDIA_ROOT publicly.**
Django checks the user's permission, then tells nginx to stream the file
(set `ATTACHMENT_X_ACCEL_PREFIX=/protected-media/`):

```nginx
client_max_body_size 30m;          # a bit above ATTACHMENT_MAX_UPLOAD_MB

location /protected-media/ {
    internal;
    alias /srv/construction-erp/media/;
}
location /media/company/ { alias /srv/construction-erp/media/company/; }  # logo only
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Static files are served by WhiteNoise (compressed + hashed names); no nginx rule needed.

## 2. Scanners

Three intake paths, all validated the same way (file type sniffed from content,
size limit, TIFF -> PDF, photo rotation + EXIF/GPS stripping, duplicate detection):

| Path | Typical user | How |
|------|--------------|-----|
| Office scanner / MFP | accounting | "Scan to folder" (SMB) -> `SCAN_INBOX_DIR` -> `import_scans` -> **Scan inbox** page |
| Phone / tablet camera | PMs on site | Document page -> Attachments -> "تصوير بالكاميرا"; several photos can be merged into one PDF |
| Desktop scanner software | anyone | Save a PDF, drag it onto the attachment drop zone (or onto the Scan inbox) |

### Scan-to-folder

1. Share `SCAN_INBOX_DIR` over SMB (Samba) to the MFP with a dedicated account.
2. Configure the MFP to save **multi-page PDF**, 200-300 dpi, grayscale. TIFF also works (converted to PDF).
3. Keep the importer running:

```ini
# /etc/systemd/system/erp-scans.service
[Service]
User=erp
WorkingDirectory=/srv/construction-erp/app
EnvironmentFile=/srv/construction-erp/app/.env
ExecStart=/srv/construction-erp/app/venv/bin/python manage.py import_scans --watch --interval 15
Restart=always
[Install]
WantedBy=multi-user.target
```

If the MFP lets users type a file name, name the scan after the document number
(`BILL-000012.pdf`, `INV-000003_signed.pdf`) and it is attached to that document
automatically. Everything else lands in the Scan inbox, where an accountant types the
document number to link it (or picks it from the "من صندوق المسح" list on the document).

Imported originals are kept in `SCAN_INBOX_DIR/processed/<date>/` (prune after your
retention period); rejected files go to `rejected/` with a `.error.txt` reason.

## 3. Backups (both, nightly, and test a restore)

```bash
pg_dump -Fc construction_erp > /backup/erp-$(date +%F).dump
rsync -a /srv/construction-erp/media/ /backup/media/
```

## 4. Go-live checklist

- [ ] `manage.py check --deploy` clean, `DEBUG=False`, strong `SECRET_KEY`
- [ ] HTTPS works everywhere, then set `SECURE_HSTS_SECONDS=31536000`
- [ ] `https://<host>/media/invoicing/...` returns 404 (attachments not public)
- [ ] Backups run and a restore was tested
- [ ] Demo users removed; every real user in exactly one group
- [ ] Login rate limiting (e.g. django-axes) if the server is reachable from the internet
