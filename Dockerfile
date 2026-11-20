# syntax=docker/dockerfile:1.7
# Construction ERP - multi-stage image
#   css        : builds Tailwind CSS (node only at build time)
#   base       : Python runtime + system libs (Ghostscript for PDF compression,
#                Pango + Arabic fonts for WeasyPrint PDFs)
#   test       : base + pytest, runs the suite against Postgres + MinIO
#   production : non-root gunicorn image with collected static files

FROM node:22-alpine3.21 AS css
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tailwind.config.js ./
COPY static/css/input.css static/css/input.css
COPY templates templates
COPY apps apps
RUN npx tailwindcss -i static/css/input.css -o static/css/output.css --minify


FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ghostscript \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
        fonts-noto-core fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 1001 app \
 && useradd --uid 1001 --gid app --create-home --home-dir /home/app app
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt


FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY --chown=app:app . .
COPY --from=css --chown=app:app /build/static/css/output.css static/css/output.css
USER app
CMD ["pytest", "-q", "-p", "no:warnings", "-p", "no:cacheprovider"]


FROM base AS production
COPY . .
COPY --from=css /build/static/css/output.css static/css/output.css
# Static files are baked into the image (served by WhiteNoise). The key below
# exists only for this build step; the real SECRET_KEY comes from .env.
RUN SECRET_KEY=collectstatic-build-only DEBUG=False USE_S3=False \
        python manage.py collectstatic --noinput -v0 \
 && chmod +x docker/entrypoint.sh \
 && chown -R app:app /app/staticfiles
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz/', timeout=4).status == 200 else 1)"
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "-c", "docker/gunicorn.conf.py"]
