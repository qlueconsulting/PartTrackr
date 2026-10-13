import os
import shutil
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.score import Score
from app.models.stem import Stem
from app.schemas.score import ScoreListResponse, ScoreResponse, StemResponse
from app.services.pipeline import run_score_pipeline

router = APIRouter(prefix="/scores", tags=["Scores"])


def _stem_to_response(stem: Stem) -> StemResponse:
    return StemResponse(
        id=stem.id,
        score_id=stem.score_id,
        part_name=stem.part_name,
        part_key=stem.part_key,
        is_accompaniment=stem.is_accompaniment,
        original_part_name=stem.original_part_name,
        duration_seconds=stem.duration_seconds,
        pitch_range=stem.pitch_range,
        measure_count=stem.measure_count,
        note_count=stem.note_count,
        audio_url=f"/api/v1/scores/{stem.score_id}/stems/{stem.id}/audio",
        midi_url=f"/api/v1/scores/{stem.score_id}/stems/{stem.id}/midi",
    )


def _score_to_response(score: Score) -> ScoreResponse:
    return ScoreResponse(
        id=score.id,
        filename=score.filename,
        title=score.title,
        composer=score.composer,
        status=score.status,
        detected_parts=score.detected_parts or [],
        error_message=score.error_message,
        error_traceback=score.error_traceback,
        processing_logs=score.processing_logs or [],
        created_at=score.created_at,
        updated_at=score.updated_at,
        stems=[_stem_to_response(st) for st in score.stems],
        xml_url=f"/api/v1/scores/{score.id}/xml" if score.xml_path else None,
        pdf_url=f"/api/v1/scores/{score.id}/file",
    )


@router.post("/upload", response_model=ScoreResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_score(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Accepts a choral score upload (.pdf, .musicxml, .xml, .mxl, .mid).
    Enqueues the processing pipeline (OMR -> notation splitting -> audio stem rendering).
    """
    allowed_exts = {".pdf", ".musicxml", ".xml", ".mxl", ".mid", ".midi"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed: {', '.join(allowed_exts)}",
        )

    score_id = str(uuid.uuid4())
    score_upload_dir = settings.UPLOAD_DIR / score_id
    score_upload_dir.mkdir(parents=True, exist_ok=True)

    dest_file = score_upload_dir / file.filename
    with open(dest_file, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    title_clean = Path(file.filename).stem.replace("_", " ").title()

    score = Score(
        id=score_id,
        filename=file.filename,
        title=title_clean,
        status="queued",
        detected_parts=[],
        original_path=str(dest_file),
    )
    db.add(score)
    db.commit()
    db.refresh(score)

    # Launch pipeline in background
    background_tasks.add_task(run_score_pipeline, score_id)

    return _score_to_response(score)


@router.get("", response_model=ScoreListResponse)
def list_scores(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    """List all ingested scores with status and metadata."""
    total = db.query(Score).count()
    scores = (
        db.query(Score)
        .order_by(Score.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return ScoreListResponse(scores=[_score_to_response(s) for s in scores], total=total)


@router.get("/{score_id}", response_model=ScoreResponse)
def get_score(score_id: str, db: Session = Depends(get_db)):
    """Retrieve score details, status, detected parts, and generated audio stems."""
    score = db.query(Score).filter(Score.id == score_id).first()
    if not score:
        raise HTTPException(status_code=404, detail="Score not found")
    return _score_to_response(score)


@router.post("/{score_id}/reprocess", response_model=ScoreResponse)
def reprocess_score(
    score_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Re-triggers OMR and notation processing pipeline for a score."""
    score = db.query(Score).filter(Score.id == score_id).first()
    if not score:
        raise HTTPException(status_code=404, detail="Score not found")

    score.status = "queued"
    score.error_message = None
    score.error_traceback = None
    score.processing_logs = []
    db.commit()

    background_tasks.add_task(run_score_pipeline, score_id)
    return _score_to_response(score)


@router.delete("/{score_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_score(score_id: str, db: Session = Depends(get_db)):
    """Deletes a score and all associated files from storage."""
    score = db.query(Score).filter(Score.id == score_id).first()
    if not score:
        raise HTTPException(status_code=404, detail="Score not found")

    # Delete storage directory
    score_dir = settings.STORAGE_DIR / score_id
    if score_dir.exists():
        shutil.rmtree(score_dir, ignore_errors=True)
    upload_dir = settings.UPLOAD_DIR / score_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)

    db.delete(score)
    db.commit()
    return None


@router.get("/{score_id}/file")
def get_original_file(score_id: str, db: Session = Depends(get_db)):
    """Serves the original uploaded file (PDF / MusicXML)."""
    score = db.query(Score).filter(Score.id == score_id).first()
    if not score or not score.original_path or not Path(score.original_path).exists():
        raise HTTPException(status_code=404, detail="Original file not found")

    media_type = "application/pdf" if score.original_path.endswith(".pdf") else "application/octet-stream"
    return FileResponse(score.original_path, filename=score.filename, media_type=media_type)


@router.get("/{score_id}/xml")
def get_score_xml(score_id: str, db: Session = Depends(get_db)):
    """Serves the generated master MusicXML file."""
    score = db.query(Score).filter(Score.id == score_id).first()
    if not score or not score.xml_path or not Path(score.xml_path).exists():
        raise HTTPException(status_code=404, detail="MusicXML file not found")

    return FileResponse(score.xml_path, filename=Path(score.xml_path).name, media_type="application/xml")
