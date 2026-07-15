FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# fileWatcherType=none: no code-reloading in prod (saves memory/CPU, avoids a watchdog
# segfault source). gatherUsageStats=false trims background work on constrained hosts.
CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", \
     "--server.fileWatcherType=none", "--browser.gatherUsageStats=false"]
