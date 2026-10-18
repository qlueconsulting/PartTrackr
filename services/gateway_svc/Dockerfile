FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY services/gateway_svc /app/services/gateway_svc

EXPOSE 8005

CMD ["uvicorn", "services.gateway_svc.main:app", "--host", "0.0.0.0", "--port", "8005"]
