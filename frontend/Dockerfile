# Build context is the REPOSITORY ROOT (not ./frontend): the dashboard runs the analytics
# engine in-process, so the image must contain the backend package too.
#   docker build -f frontend/Dockerfile -t macroshock-dashboard .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY frontend/requirements.txt ./frontend/requirements.txt
RUN pip install --no-cache-dir -r frontend/requirements.txt

# Both trees: the Streamlit app (frontend/) drives MacroShockEngine (backend/) directly.
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Drop root (least privilege). HOME must be set explicitly: Docker doesn't derive it from USER,
# and Streamlit writes its cache/config under $HOME/.streamlit.
RUN useradd -u 10001 -m appuser && chown -R appuser /app
ENV HOME=/home/appuser
USER appuser

EXPOSE 8501

# fileWatcherType=none: no code-reloading in prod (saves memory/CPU, avoids a watchdog
# segfault source). gatherUsageStats=false trims background work on constrained hosts.
CMD ["streamlit", "run", "frontend/streamlit_app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", \
     "--server.fileWatcherType=none", "--browser.gatherUsageStats=false"]
