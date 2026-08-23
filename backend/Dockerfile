FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data dir for the SQLite DB, kept OUT of the code tree (/app/data) so a mounted volume can
# never shadow the source. MACROSHOCK_DB points here in compose and on Azure.
RUN mkdir -p /app/dbdata

# Drop root: the process never needs it, and running unprivileged limits the blast radius of a
# compromise. gunicorn binds 5000 (>1024, no privilege needed); the app only writes /app/dbdata.
RUN useradd -u 10001 -m appuser && chown -R appuser /app
USER appuser

EXPOSE 5000

# Seed the SQLite database (idempotent) then serve the API with gunicorn.
CMD ["sh", "-c", "python -m data.seed && gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 60 'app:app'"]
