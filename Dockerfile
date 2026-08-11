FROM python:3.12-slim

ARG RADIOCHARTS_VERSION=dev
ARG RADIOCHARTS_GIT_SHA=unknown
ARG RADIOCHARTS_BUILD_DATE=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Warsaw \
    RADIOCHARTS_VERSION=${RADIOCHARTS_VERSION} \
    RADIOCHARTS_GIT_SHA=${RADIOCHARTS_GIT_SHA} \
    RADIOCHARTS_BUILD_DATE=${RADIOCHARTS_BUILD_DATE}

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY radiocharts ./radiocharts
COPY config ./config
COPY sample_imports ./sample_imports
COPY VERSION ./VERSION

RUN mkdir -p /app/data /app/logs

ENV PYTHONPATH=/app
EXPOSE 8501

CMD ["streamlit", "run", "radiocharts/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
