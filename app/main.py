import logging
import os
from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.api.router import api_router
from app.config import settings
from app.database import Base, engine, get_db
from app.models.score import Score
from app.models.stem import Stem
from app.services.pipeline import run_score_pipeline

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("parttrackr")

# Initialize database schema
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Choral rehearsal and notation processing microservice with multi-track Web Audio player",
)

# Enable CORS for Web Audio API and external integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Router
app.include_router(api_router)

# Mount static files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/health")
def health_check():
    """Service health and diagnostics check."""
    from app.services.omr import omr_engine
    from app.services.synthesis import audio_synthesizer

    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.VERSION,
        "omr_engine_available": omr_engine.is_available(),
        "fluidsynth_available": audio_synthesizer.has_fluidsynth(),
        "ffmpeg_available": audio_synthesizer.has_ffmpeg(),
        "storage_dir": str(settings.STORAGE_DIR),
    }


@app.get("/", response_class=HTMLResponse)
def serve_index():
    """Serves the PartTrackr test harness and rehearsal player UI."""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>PartTrackr UI initializing...</h1>")


@app.post("/api/v1/scores/load-sample")
def load_sample_choral_score(db: Session = Depends(get_db)):
    """
    Creates and processes a rich sample choral score (SATB + Piano Accompaniment)
    so users can immediately experience the rehearsal player without needing to upload files.
    """
    sample_file = Path(__file__).parent.parent / "sample_scores" / "bach_satb_piano.musicxml"
    if not sample_file.exists():
        # Generate sample score if not present
        from sample_scores.create_samples import generate_satb_piano_xml
        sample_file = generate_satb_piano_xml()

    import uuid
    score_id = str(uuid.uuid4())
    score_upload_dir = settings.UPLOAD_DIR / score_id
    score_upload_dir.mkdir(parents=True, exist_ok=True)

    dest_file = score_upload_dir / "bach_satb_piano.musicxml"
    import shutil
    shutil.copy2(sample_file, dest_file)

    score = Score(
        id=score_id,
        filename="bach_satb_piano.musicxml",
        title="O Sacred Head Now Wounded (SATB & Piano)",
        composer="J.S. Bach",
        status="queued",
        detected_parts=[],
        original_path=str(dest_file),
    )
    db.add(score)
    db.commit()
    db.refresh(score)

    # Process immediately
    run_score_pipeline(score_id)

    db.refresh(score)
    from app.api.endpoints.scores import _score_to_response
    return _score_to_response(score)
