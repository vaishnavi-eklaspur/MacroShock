FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Build context is the repo ROOT (see docker-compose.yml / deploy/azure/deploy.sh): the dashboard
# runs the analytics engine IN-PROCESS, so the image needs the backend package next to the UI code.
COPY frontend/requirements.txt frontend/requirements.txt
RUN pip install --no-cache-dir -r frontend/requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

# Drop root (least privilege). HOME must be set explicitly: Docker doesn't derive it from USER,
# and Streamlit writes its cache/config under $HOME/.streamlit.
RUN useradd -u 10001 -m appuser && chown -R appuser /app
ENV HOME=/home/appuser
USER appuser

# Run from the dashboard dir so Streamlit loads frontend/.streamlit/config.toml and the app's
# __file__-relative import of ../backend resolves to /app/backend.
WORKDIR /app/frontend

EXPOSE 8501

# fileWatcherType=none: no code-reloading in prod (saves memory/CPU, avoids a watchdog
# segfault source). gatherUsageStats=false trims background work on constrained hosts.
CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", \
     "--server.fileWatcherType=none", "--browser.gatherUsageStats=false"]
