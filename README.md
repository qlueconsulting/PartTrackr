# PartTrackr 🎵

**Choral Rehearsal & Notation Processing Microservice**  
Repository: `https://github.com/qlueconsulting/PartTrackr`  
Deployment: Dockerized FastAPI Microservice (Local Dev -> Supabase Production Target)

---

## Overview

**PartTrackr** is an automated choral rehearsal and notation processing microservice with a local web-based testing harness. It allows choral singers and directors to upload sheet music in PDF (or MusicXML/MXL) format, ingest and parse the score into discrete vocal and accompaniment parts via Optical Music Recognition (OMR) and symbolic notation processing, and interactively rehearse the piece via a synchronized multi-track audio web player.

### Key Capabilities
1. **Choral Score Ingestion**:
   - Ingestion of PDF choral scores via headless **Audiveris** Optical Music Recognition (OMR).
   - Direct ingestion of **MusicXML** (`.musicxml`, `.xml`, `.mxl`) and **MIDI** (`.mid`) files.
2. **11-Part Standard Choral Taxonomy**:
   - Discrete part extraction and normalization:
     - `Piano Score` (Accompaniment)
     - `Soprano I`, `Soprano II`
     - `Alto I`, `Alto II`
     - `Tenor I`, `Tenor II`
     - `Baritone I`, `Baritone II`
     - `Bass I`, `Bass II`
   - **Intelligent Aggregation & Fallbacks**: Collapses and maps `SATB`, `SAB`, `SSA`, or `TTBB` scores to their primary registers without failing.
   - **Polyphonic Voice & Divisi Splitting**: Automatically splits shared staves (e.g. Women: Soprano up-stem / Alto down-stem; Men: Tenor up-stem / Bass down-stem) and chord divisi into separate parts.
3. **High-Quality Audio Stem Synthesis**:
   - FluidSynth synthesis using clean GM SoundFonts (`FluidR3_GM.sf2`).
   - Built-in additive harmonic synthesizer fallback for local dev / environments without FluidSynth installed.
   - FFmpeg audio encoding to MP3 with native WAV streaming support.
4. **Interactive Synchronized Multi-Track Web Rehearsal Player**:
   - Built-in test harness served directly from FastAPI (`/`).
   - **Sample-accurate synchronized playback** across all detected stems via Web Audio API.
   - **Rehearsal Part Focus Engine**:
     - Target Part Dropdown (`S1`, `S2`, `A1`, `A2`, `T1`, `T2`, `Bar1`, `Bar2`, `B1`, `B2`, `Piano`).
     - **"Emphasize Part"** Mode: Boost target part up to 200% while attenuating background vocal parts to keep harmonic context.
     - **"Solo / Isolate Part"** Mode: Isolate the target part while silencing other voices.
     - **Quick Piano Toggle**: 1-click on/off switch for piano accompaniment.
     - Master transport (Play, Pause, Stop, Seek, Master Volume).
     - Individual stem channel strips with Volume, Pan, Mute, Solo, and direct WAV/MIDI download buttons.
   - **Score Notation Preview**: Interactive sheet music rendering powered by OpenSheetMusicDisplay (OSMD).

---

## Architecture & Technology Stack

| Component | Technology |
|---|---|
| **Backend Framework** | FastAPI (Python 3.10 / 3.11) with Uvicorn |
| **OMR Engine** | Headless Audiveris CLI (batch mode) |
| **Symbolic Notation** | music21 |
| **Audio Rendering** | FluidSynth + SoundFont (`FluidR3_GM.sf2`) & Built-in Harmonic Synthesizer Fallback |
| **Audio Encoding** | FFmpeg / pydub |
| **Database** | SQLite (`parttrackr_local.db`) with SQLAlchemy ORM (mocking Supabase local persistence) |
| **Frontend Test Harness** | Vanilla HTML5 / ES6 JavaScript + Tailwind CSS CDN + Web Audio API + OSMD |
| **Containerization** | Multi-stage Dockerfile (Ubuntu 22.04 LTS, OpenJDK 17 headless, FluidSynth, FFmpeg, Python) |

---

## Quickstart & Deployment

### 1. Production Server Deployment (`docker pull`)

GitHub Actions automatically builds and publishes the production image to **GitHub Container Registry (GHCR)** on every push to `main` and release tag.

To deploy on any server without building from source:

#### Option A: Direct Docker CLI
```bash
# Pull prebuilt image from GHCR
docker pull ghcr.io/qlueconsulting/parttrackr:latest

# Run container with persistent storage
docker run -d \
  --name parttrackr \
  --restart unless-stopped \
  -p 8000:8000 \
  -v $(pwd)/storage:/app/storage \
  ghcr.io/qlueconsulting/parttrackr:latest
```

#### Option B: Docker Compose (Production)
```bash
# Pull and start using the production compose file
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

---

### 2. Local Container Build (Development)

```bash
# Clone the repository
git clone https://github.com/qlueconsulting/PartTrackr.git
cd PartTrackr

# Build and start container locally
docker compose up --build
```
Navigate to `http://localhost:8000` in your browser.

---

### 3. Running Locally (Python Virtual Environment)

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the development server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open `http://localhost:8000`. You can click **"Load Bach SATB Sample"** for instant 1-click rehearsal playback!

---

## API Reference

### Scores API (`/api/v1/scores`)

- `POST /api/v1/scores/upload`: Ingest a PDF, MusicXML, MXL, or MIDI score file. Returns `202 Accepted` with initial status `queued`.
- `GET /api/v1/scores`: List all ingested scores, statuses, and detected parts.
- `GET /api/v1/scores/{score_id}`: Retrieve score details, status, detected parts, and generated stem metadata.
- `POST /api/v1/scores/{score_id}/reprocess`: Re-trigger OMR, notation parsing, and synthesis.
- `DELETE /api/v1/scores/{score_id}`: Delete a score and all generated audio/XML/MIDI storage assets.
- `GET /api/v1/scores/{score_id}/file`: Download raw uploaded source file.
- `GET /api/v1/scores/{score_id}/xml`: Download master MusicXML file.
- `POST /api/v1/scores/load-sample`: Ingest and synthesize the built-in Bach SATB + Piano rehearsal sample score.

### Stems API (`/api/v1/scores/{score_id}/stems`)

- `GET /api/v1/scores/{score_id}/stems/{stem_id}/audio`: Stream stem audio file (WAV or MP3) with byte-range support for Web Audio API.
- `GET /api/v1/scores/{score_id}/stems/{stem_id}/midi`: Download isolated General MIDI file for the stem.

### Health Check

- `GET /health`: Health and diagnostics status (checks availability of Audiveris, FluidSynth, and FFmpeg).

---

## Running the Test Suite

```bash
pytest -v
```
PartTrackr includes unit and integration tests covering:
- Standard 11-part choral taxonomy
- SATB + Piano part extraction
- Polyphonic stem direction voice splitting (Treble staff: Soprano up, Alto down)
- Choral chord divisi splitting
- SSA, TTBB, and SAB register aggregation fallbacks
- Unnamed parts register inference
- 44.1kHz stereo audio stem synthesis
- All FastAPI endpoints (upload, audio streaming, MIDI download, deletion)
