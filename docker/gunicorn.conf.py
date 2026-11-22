"""gunicorn settings (values overridable through the environment)."""
import multiprocessing
import os

bind = '0.0.0.0:8000'
workers = int(os.environ.get('GUNICORN_WORKERS', min(4, multiprocessing.cpu_count() * 2 + 1)))
threads = int(os.environ.get('GUNICORN_THREADS', 2))
# Large scanned PDFs are compressed during upload; give them time.
timeout = int(os.environ.get('GUNICORN_TIMEOUT', 180))
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 100
worker_tmp_dir = '/tmp'
forwarded_allow_ips = os.environ.get('FORWARDED_ALLOW_IPS', '*')  # VPS: only the cloudflared container
accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('LOG_LEVEL', 'info').lower()
