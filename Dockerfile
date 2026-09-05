# Playwright publishes a Python image with Chromium and all browser OS
# dependencies preinstalled. Keep this version in sync with requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.54.0-noble

ARG RADIOCHARTS_VERSION=dev
ARG RADIOCHARTS_GIT_SHA=unknown
ARG RADIOCHARTS_BUILD_DATE=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Warsaw \
    RADIOCHARTS_VERSION=${RADIOCHARTS_VERSION} \
    RADIOCHARTS_GIT_SHA=${RADIOCHARTS_GIT_SHA} \
    RADIOCHARTS_BUILD_DATE=${RADIOCHARTS_BUILD_DATE} \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# The base image already contains Chromium and its OS dependencies.
# Install only RadioCharts' Python dependencies; requirements.txt pins
# playwright==1.54.0 to match the base image.
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY radiocharts ./radiocharts
COPY config ./config
COPY VERSION ./VERSION
COPY dist/android /app/android

RUN mkdir -p /app/data /app/logs

ENV PYTHONPATH=/app
EXPOSE 8501 8502

CMD ["streamlit", "run", "radiocharts/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
