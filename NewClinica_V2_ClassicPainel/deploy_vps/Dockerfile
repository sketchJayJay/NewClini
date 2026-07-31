FROM python:3.12-slim

# Prevents Python from writing pyc files and buffers
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (optional but helpful)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# Create data dir inside container (will be mounted as volume in compose)
RUN mkdir -p /data

# Default: gunicorn behind reverse proxy
ENV PORT=8000
CMD ["gunicorn", "-b", "0.0.0.0:8000", "wsgi:app", "--workers", "2", "--threads", "4", "--timeout", "120"]
