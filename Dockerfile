FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Warsaw

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY radiocharts ./radiocharts
COPY config ./config
COPY sample_imports ./sample_imports

RUN mkdir -p /app/data /app/logs

ENV PYTHONPATH=/app
EXPOSE 8501

CMD ["streamlit", "run", "radiocharts/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
