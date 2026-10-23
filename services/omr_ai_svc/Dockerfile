FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    _JAVA_OPTIONS="-Djava.awt.headless=true" \
    JAVA_TOOL_OPTIONS="-Djava.awt.headless=true" \
    LD_LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:/usr/lib/aarch64-linux-gnu:/usr/lib" \
    AUDIVERIS_VERSION=5.11.0

# Install Java headless, Ghostscript (required for Audiveris PDF rasterization),
# Tesseract OCR, zstd (required for deb extraction), and GTK3/AWT headless graphics dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    zstd \
    ghostscript \
    default-jre-headless \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgtk-3-0 \
    libgl1 \
    libglib2.0-0 \
    libxtst6 \
    libxrender1 \
    libxi6 \
    libasound2 \
    libfontconfig1 \
    libfreetype6 \
    libxext6 \
    libbsd0 \
    libmd0 \
    libx11-6 \
    libxau6 \
    libxcb1 \
    libxdmcp6 \
    xdg-utils \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Ensure JNA can find libgtk-3.so, libgdk-3.so, and glib libraries for Audiveris HiDPI scaling
RUN for so_name in "libgtk-3" "libgdk-3" "libgobject-2.0" "libglib-2.0"; do \
        for so_file in $(find /usr/lib -name "${so_name}.so.0*" 2>/dev/null); do \
            dir=$(dirname "$so_file"); \
            ln -sf "$so_file" "$dir/${so_name}.so"; \
            ln -sf "$so_file" "/usr/lib/${so_name}.so"; \
        done; \
    done && \
    ldconfig || true

# Install Audiveris headless OMR CLI and verify executable works
RUN mkdir -p /usr/share/desktop-directories /opt/audiveris && \
    wget -q https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/Audiveris-${AUDIVERIS_VERSION}-ubuntu22.04-x86_64.deb -O /tmp/audiveris.deb && \
    dpkg-deb -x /tmp/audiveris.deb / && \
    rm -f /tmp/audiveris.deb && \
    chmod +x /opt/audiveris/bin/Audiveris && \
    ln -sfn /opt/audiveris/bin/Audiveris /usr/local/bin/audiveris && \
    ln -sfn /opt/audiveris/bin/Audiveris /usr/bin/audiveris && \
    audiveris -batch -help

COPY services/omr_ai_svc/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY services/omr_ai_svc /app/services/omr_ai_svc

EXPOSE 8007

CMD ["uvicorn", "services.omr_ai_svc.main:app", "--host", "0.0.0.0", "--port", "8007"]
