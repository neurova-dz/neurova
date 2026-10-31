FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# System deps required by ML wheels and WeasyPrint
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt && \
    pip install gunicorn

COPY . /app

ENV FLASK_APP=run.py \
    NEUROVA_ENV=production \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=4s --retries=3 \
  CMD curl -fsS http://localhost:${PORT}/healthz || exit 1

CMD ["gunicorn", "-w", "3", "-k", "gthread", "--threads", "4", "--bind", "0.0.0.0:8000", "--timeout", "120", "run:app"]
