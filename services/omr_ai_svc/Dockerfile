FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    _JAVA_OPTIONS="-Djava.awt.headless=true" \
    JAVA_TOOL_OPTIONS="-Djava.awt.headless=true" \
    AUDIVERIS_VERSION=5.11.0

# Install Java headless, Tesseract OCR, and headless graphics/AWT dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    default-jre-headless \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    libxtst6 \
    libxrender1 \
    libxi6 \
    libasound2 \
    libfontconfig1 \
    libfreetype6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Install Audiveris headless OMR CLI with safe download & fallback
RUN mkdir -p /usr/share/desktop-directories /opt/audiveris && \
    (wget -q https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/Audiveris-${AUDIVERIS_VERSION}-ubuntu22.04-x86_64.deb -O /tmp/audiveris.deb 2>/dev/null || true) && \
    if [ -f /tmp/audiveris.deb ] && [ -s /tmp/audiveris.deb ]; then \
        dpkg-deb -x /tmp/audiveris.deb / && \
        rm -f /tmp/audiveris.deb && \
        REAL_BIN=$(find /opt -type f -name "Audiveris" 2>/dev/null | head -n 1) && \
        if [ -n "$REAL_BIN" ]; then \
            chmod +x "$REAL_BIN" && \
            ln -sfn "$REAL_BIN" /usr/local/bin/audiveris && \
            ln -sfn "$REAL_BIN" /usr/bin/audiveris; \
        fi \
    else \
        rm -f /tmp/audiveris.deb; \
    fi

COPY services/omr_ai_svc/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY services/omr_ai_svc /app/services/omr_ai_svc

EXPOSE 8007

CMD ["uvicorn", "services.omr_ai_svc.main:app", "--host", "0.0.0.0", "--port", "8007"]
