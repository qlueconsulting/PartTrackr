FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY services/voice_router_svc/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY services/voice_router_svc /app/services/voice_router_svc

EXPOSE 8008

CMD ["uvicorn", "services.voice_router_svc.main:app", "--host", "0.0.0.0", "--port", "8008"]
