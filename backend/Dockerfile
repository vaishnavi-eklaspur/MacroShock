# ---- build stage: resolve and install dependencies ------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
# Install into a relocatable prefix so the runtime image receives only the installed
# packages -- no pip cache, no build tooling, no wheels left behind.
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- runtime stage --------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# /install mirrors the /usr/local layout, so console scripts (gunicorn, celery) land on PATH.
COPY --from=builder /install /usr/local

WORKDIR /app
COPY . .

# Data dir for the SQLite DB, kept OUT of the code tree (/app/data) so a mounted volume can
# never shadow the source. MACROSHOCK_DB points here in compose and on Kubernetes.
RUN mkdir -p /app/dbdata

# Drop root: the process never needs it, and running unprivileged limits the blast radius of a
# compromise. gunicorn binds 5000 (>1024, no privilege needed); the app only writes /app/dbdata.
RUN useradd -u 10001 -m appuser && chown -R appuser /app
USER appuser

EXPOSE 5000

# Seed the SQLite database (idempotent) then serve the API with gunicorn.
CMD ["sh", "-c", "python -m data.seed && gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 60 'app:app'"]
