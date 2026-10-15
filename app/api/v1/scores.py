from datetime import datetime
import json
import logging
from pathlib import Path
import shutil
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.score import Score
from app.schemas.score import (
    ScoreResponse,
    ScoreSummary,
    StemInfo,
    MeasureInfo,
    AuditReport,
)
from app.services.omr_service import OMREngine
from app.services.notation_processor import NotationProcessor, STEM_TAXONOMY, STEM_METADATA
from app.services.audio_synthesizer import AudioSynthesizer
from app.services.audit_service import ScoreAuditService
from app.services.sample_scores import create_sample_satb_with_piano, create_sample_unison_choral

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scores", tags=["Scores"])

omr_engine = OMREngine()
audio_synth = AudioSynthesizer()

def _process_score_pipeline(score_id: str, original_file_path: Path, filename: str, db: Session) -> Score:
    """Internal orchestration pipeline for a score."""
    score_dir = settings.STORAGE_DIR / score_id
    orig_dir = score_dir / "original"
    omr_dir = score_dir / "omr"
    stems_dir = score_dir / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)

    db_score = db.query(Score).filter(Score.id == score_id).first()
    if not db_score:
        raise HTTPException(status_code=404, detail="Score record not found")

    try:
        db_score.status = "processing"
        db_score.status_message = "Performing optical music recognition and format parsing..."
        db.commit()

        # Step 1: OMR / Ingestion
        musicxml_path = omr_engine.process_file(original_file_path, omr_dir)

        # Step 2: Notation Analysis & Dynamic Choral Voice Routing
        db_score.status_message = "Analyzing score notation, applying dynamic bracket routing, and clamping measures..."
        db.commit()

        processor = NotationProcessor(musicxml_path)
        stem_scores, analysis = processor.extract_all_stems()

        total_measures = len(analysis)
        total_duration = sum(a["duration_seconds"] for a in analysis)
        first_m = analysis[0] if analysis else None
        time_sig = first_m["time_signature"] if first_m else "4/4"
        tempo_val = first_m["tempo_bpm"] if first_m else 120.0

        db_score.title = processor.title
        db_score.composer = processor.composer
        db_score.measure_count = total_measures
        db_score.total_duration_seconds = round(total_duration, 3)
        db_score.time_signature = time_sig
        db_score.tempo_bpm = tempo_val

        # Step 3: Export MusicXML, MIDI, and Synthesize Audio Stems
        db_score.status_message = "Rendering isolated 11 audio stems with soundfont synthesis..."
        db.commit()

        stems_dict = {}

        for stem_name in STEM_TAXONOMY:
            sc = stem_scores[stem_name]
            meta = STEM_METADATA[stem_name]

            # Export standalone MusicXML
            mxml_path = stems_dir / f"{stem_name}.musicxml"
            sc.write("musicxml", fp=str(mxml_path))

            # Export standalone MIDI
            mid_path = stems_dir / f"{stem_name}.mid"
            sc.write("midi", fp=str(mid_path))

            # Render Audio (WAV & MP3)
            wav_path, mp3_path = audio_synth.render_stem(
                midi_path=mid_path,
                stem_name=stem_name,
                output_dir=stems_dir,
                target_duration_seconds=total_duration
            )

            # Count sounding notes
            note_count = len(sc.parts[0].flatten().notes)
            is_active = note_count > 0

            stems_dict[stem_name] = {
                "name": stem_name,
                "display_name": meta["display"],
                "category": meta["category"],
                "audio_url": f"/api/v1/scores/{score_id}/stems/{stem_name}.mp3",
                "musicxml_url": f"/api/v1/scores/{score_id}/stems/{stem_name}.musicxml",
                "midi_url": f"/api/v1/scores/{score_id}/stems/{stem_name}.mid",
                "note_count": note_count,
                "is_active_in_score": is_active,
                "default_pan": meta["default_pan"]
            }

        # Step 4: Audit Checks
        db_score.status_message = "Running score integrity audit and lockstep verification..."
        db.commit()

        audit_report = ScoreAuditService.audit_score(
            stems=stem_scores,
            analysis=analysis,
            original_score=processor.raw_score
        )

        # Finalize DB Score
        db_score.status = "completed"
        db_score.status_message = "Processing completed successfully."
        db_score.stems_metadata = stems_dict
        db_score.analysis_json = analysis
        db_score.audit_report = audit_report.model_dump()
        db.commit()
        db.refresh(db_score)

        return db_score

    except Exception as e:
        logger.exception(f"Pipeline error processing score {score_id}: {e}")
        db_score.status = "failed"
        db_score.status_message = str(e)
        db.commit()
        db.refresh(db_score)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Score processing failed: {str(e)}"
        )

@router.post("/upload", response_model=ScoreResponse)
async def upload_score(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Uploads a choral sheet music file (.pdf, .musicxml, .xml, .mxl, .mid),
    extracts the 11 rehearsal stems, renders audio, and returns measure analysis.
    """
    allowed_exts = [".pdf", ".musicxml", ".xml", ".mxl", ".mid", ".midi"]
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{file_ext}'. Allowed: {', '.join(allowed_exts)}"
        )

    score_id = str(uuid.uuid4())
    orig_dir = settings.STORAGE_DIR / score_id / "original"
    orig_dir.mkdir(parents=True, exist_ok=True)
    orig_file_path = orig_dir / file.filename

    with open(orig_file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    db_score = Score(
        id=score_id,
        title=Path(file.filename).stem.replace("_", " ").title(),
        original_filename=file.filename,
        file_type=file_ext.lstrip("."),
        status="pending",
        status_message="File uploaded, preparing pipeline..."
    )
    db.add(db_score)
    db.commit()
    db.refresh(db_score)

    # Process pipeline
    processed_score = _process_score_pipeline(score_id, orig_file_path, file.filename, db)

    return ScoreResponse(
        id=processed_score.id,
        title=processed_score.title,
        composer=processed_score.composer,
        original_filename=processed_score.original_filename,
        file_type=processed_score.file_type,
        status=processed_score.status,
        status_message=processed_score.status_message,
        created_at=processed_score.created_at,
        measure_count=processed_score.measure_count,
        total_duration_seconds=processed_score.total_duration_seconds,
        time_signature=processed_score.time_signature,
        tempo_bpm=processed_score.tempo_bpm,
        stems=processed_score.stems_metadata,
        analysis=processed_score.analysis_json,
        audit=processed_score.audit_report
    )

@router.post("/sample/{sample_key}", response_model=ScoreResponse)
async def load_sample_score(
    sample_key: str,
    db: Session = Depends(get_db)
):
    """
    Instantly loads and processes pre-built choral test scores:
    - 'anthem': SATB + Piano Anthem of Hope with intro/interlude & divisi
    - 'unison': Unison and Divisi Choral Study (SA/TB unison lines)
    """
    score_id = str(uuid.uuid4())
    orig_dir = settings.STORAGE_DIR / score_id / "original"
    orig_dir.mkdir(parents=True, exist_ok=True)

    if sample_key == "unison":
        filename = "unison_divisi_study.musicxml"
        file_path = orig_dir / filename
        create_sample_unison_choral(file_path)
        title = "Unison and Divisi Choral Study"
    else:
        filename = "choral_anthem_of_hope.musicxml"
        file_path = orig_dir / filename
        create_sample_satb_with_piano(file_path)
        title = "Choral Anthem of Hope"

    db_score = Score(
        id=score_id,
        title=title,
        composer="PartTrackr Sample Library",
        original_filename=filename,
        file_type="musicxml",
        status="pending",
        status_message="Initializing sample score..."
    )
    db.add(db_score)
    db.commit()
    db.refresh(db_score)

    processed_score = _process_score_pipeline(score_id, file_path, filename, db)

    return ScoreResponse(
        id=processed_score.id,
        title=processed_score.title,
        composer=processed_score.composer,
        original_filename=processed_score.original_filename,
        file_type=processed_score.file_type,
        status=processed_score.status,
        status_message=processed_score.status_message,
        created_at=processed_score.created_at,
        measure_count=processed_score.measure_count,
        total_duration_seconds=processed_score.total_duration_seconds,
        time_signature=processed_score.time_signature,
        tempo_bpm=processed_score.tempo_bpm,
        stems=processed_score.stems_metadata,
        analysis=processed_score.analysis_json,
        audit=processed_score.audit_report
    )

@router.get("", response_model=List[ScoreSummary])
def list_scores(db: Session = Depends(get_db)):
    """Lists all uploaded and processed scores."""
    scores = db.query(Score).order_by(Score.created_at.desc()).all()
    summaries = []
    for s in scores:
        active_count = sum(1 for item in s.stems_metadata.values() if item.get("is_active_in_score", False))
        summaries.append(ScoreSummary(
            id=s.id,
            title=s.title,
            composer=s.composer or "Unknown",
            original_filename=s.original_filename,
            file_type=s.file_type,
            status=s.status,
            created_at=s.created_at,
            measure_count=s.measure_count,
            total_duration_seconds=s.total_duration_seconds,
            active_stems_count=active_count
        ))
    return summaries

@router.get("/{score_id}", response_model=ScoreResponse)
def get_score(score_id: str, db: Session = Depends(get_db)):
    """Retrieves detailed score data, 11 stems metadata, measure analysis, and audit."""
    s = db.query(Score).filter(Score.id == score_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Score not found")

    return ScoreResponse(
        id=s.id,
        title=s.title,
        composer=s.composer or "Unknown",
        original_filename=s.original_filename,
        file_type=s.file_type,
        status=s.status,
        status_message=s.status_message,
        created_at=s.created_at,
        measure_count=s.measure_count,
        total_duration_seconds=s.total_duration_seconds,
        time_signature=s.time_signature,
        tempo_bpm=s.tempo_bpm,
        stems=s.stems_metadata,
        analysis=s.analysis_json,
        audit=s.audit_report
    )

@router.get("/{score_id}/stems/{file_name}")
def download_stem(score_id: str, file_name: str):
    """
    Streams audio files (.mp3, .wav) or downloads notation (.musicxml, .mid)
    for a specific stem.
    """
    stem_file = settings.STORAGE_DIR / score_id / "stems" / file_name
    if not stem_file.exists():
        raise HTTPException(status_code=404, detail=f"Stem asset '{file_name}' not found")

    ext = stem_file.suffix.lower()
    media_types = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".musicxml": "application/vnd.recordare.musicxml+xml",
        ".xml": "application/xml",
        ".mid": "audio/midi",
        ".midi": "audio/midi",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(
        path=str(stem_file),
        media_type=media_type,
        filename=file_name
    )
