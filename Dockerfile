# ==============================================================================
# PartTrackr Microservice - Multi-stage Production Dockerfile
# Base OS: Ubuntu 22.04 LTS with OpenJDK 17 headless, FluidSynth, Audiveris OMR,
# FFmpeg, Poppler, and Python 3.11
# ==============================================================================

# Stage 1: Build React Frontend
FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Production Backend Microservice
FROM ubuntu:22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    PATH="/usr/lib/jvm/java-17-openjdk-amd64/bin:$PATH" \
    STORAGE_DIR=/app/storage \
    SOUNDFONT_PATH=/usr/share/sounds/sf2/FluidR3_GM.sf2 \
    AUDIVERIS_BIN=/usr/local/bin/audiveris \
    FLUIDSYNTH_BIN=/usr/bin/fluidsynth \
    FFMPEG_BIN=/usr/bin/ffmpeg \
    LD_LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:/usr/lib/aarch64-linux-gnu:/usr/lib"

# Install system dependencies:
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    curl \
    wget \
    unzip \
    git \
    openjdk-17-jre \
    libgtk-3-0 \
    libxtst6 \
    libxrender1 \
    libxi6 \
    libasound2 \
    libfontconfig1 \
    libgl1 \
    fluidsynth \
    fluid-soundfont-gm \
    libsndfile1 \
    ffmpeg \
    poppler-utils \
    imagemagick \
    tesseract-ocr \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Symlink python3.11 as default python
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Configure SoundFont symlink for FluidR3_GM.sf2
RUN mkdir -p /usr/share/sounds/sf2 && \
    if [ -f /usr/share/sounds/sf2/FluidR3_GM.sf2 ]; then \
        echo "FluidR3_GM.sf2 already present"; \
    elif [ -f /usr/share/sounds/sf2/default-GM.sf2 ]; then \
        ln -sfn /usr/share/sounds/sf2/default-GM.sf2 /usr/share/sounds/sf2/FluidR3_GM.sf2 || true; \
    else \
        find /usr/share/sounds/sf2 -name "*.sf2" -exec ln -sfn {} /usr/share/sounds/sf2/FluidR3_GM.sf2 \; || true; \
    fi

# Install Audiveris OMR CLI for Ubuntu 22.04
ENV AUDIVERIS_VERSION=5.11.0
ENV _JAVA_OPTIONS="-Djava.awt.headless=true"
ENV JAVA_TOOL_OPTIONS="-Djava.awt.headless=true"
RUN mkdir -p /usr/share/desktop-directories /opt/audiveris /opt/Audiveris && \
    wget -q https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/Audiveris-${AUDIVERIS_VERSION}-ubuntu22.04-x86_64.deb -O /tmp/audiveris.deb && \
    (dpkg -i /tmp/audiveris.deb || apt-get install -f -y || dpkg-deb -x /tmp/audiveris.deb /) && \
    rm -f /tmp/audiveris.deb && \
    REAL_BIN=$(find /opt /usr -type f \( -name "Audiveris" -o -name "audiveris" \) ! -name "*.deb" 2>/dev/null | head -n 1) && \
    if [ -n "$REAL_BIN" ]; then \
        chmod +x "$REAL_BIN"; \
        ln -sfn "$REAL_BIN" /usr/local/bin/audiveris; \
        ln -sfn "$REAL_BIN" /usr/bin/audiveris; \
        ln -sfn "$REAL_BIN" /usr/local/bin/Audiveris; \
    fi

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY app /app/app
COPY storage /app/storage

# Copy built frontend assets from Stage 1
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
