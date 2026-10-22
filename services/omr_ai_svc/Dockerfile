FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV _JAVA_OPTIONS="-Djava.awt.headless=true"
ENV JAVA_TOOL_OPTIONS="-Djava.awt.headless=true"
ENV PATH="/opt/audiveris/bin:${PATH}"

# Install Java 17 headless, Tesseract OCR, and graphical libs needed by headless Audiveris
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    openjdk-17-jre-headless \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Audiveris 5.3 headless binary
RUN mkdir -p /opt/audiveris && \
    curl -fsSL -o /tmp/audiveris.tar.gz https://github.com/Audiveris/audiveris/releases/download/5.3.1/audiveris-5.3.1.tar.gz 2>/dev/null || true && \
    if [ -f /tmp/audiveris.tar.gz ] && [ -s /tmp/audiveris.tar.gz ]; then \
        tar -xzf /tmp/audiveris.tar.gz -C /opt/audiveris --strip-components=1 && rm /tmp/audiveris.tar.gz; \
    else \
        rm -f /tmp/audiveris.tar.gz; \
    fi

COPY services/omr_ai_svc/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY services/omr_ai_svc /app/services/omr_ai_svc

EXPOSE 8007

CMD ["uvicorn", "services.omr_ai_svc.main:app", "--host", "0.0.0.0", "--port", "8007"]
