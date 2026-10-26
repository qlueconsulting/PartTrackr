import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
from typing import Optional, Dict, Any, List
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from services.gateway_svc.database import init_db, Job
from services.gateway_svc.orchestrator import PipelineOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("gateway_svc")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", str(BASE_DIR / "storage")))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = STORAGE_DIR / "parttrackr_jobs.db"
SessionFactory = init_db(DB_PATH)

router = APIRouter()

app = FastAPI(
    title="PartTrackr - API Gateway Service",
    version="2.0.0",
    description="Pipeline Orchestrator & Job Queue for Choral OMR & 11-Part Voice Separation",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionFactory()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "gateway-svc",
        "port": 8005,
        "storage_dir": str(STORAGE_DIR),
    }


class ScoreHintsRequest(BaseModel):
    time_signature: Optional[str] = None
    tempo_bpm: Optional[float] = None
    choral_voicing: Optional[str] = None
    accompaniment_type: Optional[str] = None
    staves_per_system: Optional[int] = None
    total_measures: Optional[int] = None
    custom_instructions: Optional[str] = None
    part_layout_summary: Optional[str] = None
    save_as_template: Optional[bool] = True


@router.post("/api/v1/jobs/upload")
async def upload_pdf_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    custom_instructions: Optional[str] = Form(None),
    auto_start: Optional[bool] = Form(False),
    db: Session = Depends(get_db)
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF sheet music files are supported in this pipeline.")

    job_id = str(uuid.uuid4())[:8]
    job_dir = STORAGE_DIR / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    pdf_dest = job_dir / file.filename
    with open(pdf_dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Run quick cursory preflight analysis on page 1
    preflight_hints = {}
    try:
        from services.pdf_layout_svc.layout_engine import PDFLayoutEngine
        preflight_hints = PDFLayoutEngine.preflight_analysis(pdf_dest)
    except Exception as e:
        logger.warning(f"Initial preflight check failed for {file.filename}: {e}")

    final_title = preflight_hints.get("title") or Path(file.filename).stem.replace("_", " ").title()
    final_composer = preflight_hints.get("composer") or "Unknown Composer"
    page_count = preflight_hints.get("page_count", 1)

    initial_status = "pending" if auto_start else "awaiting_verification"
    initial_msg = (
        "File uploaded, initializing pipeline..."
        if auto_start
        else "Initial Page 1 pre-flight scan complete. Awaiting user verification in AI Helps..."
    )

    job = Job(
        id=job_id,
        original_filename=file.filename,
        pdf_path=str(pdf_dest),
        title=final_title,
        composer=final_composer,
        page_count=page_count,
        status=initial_status,
        stage_message=initial_msg,
        score_hints=preflight_hints
    )
    db.add(job)
    db.commit()

    if auto_start:
        effective_instructions = custom_instructions or preflight_hints.get("custom_instructions")
        background_tasks.add_task(
            PipelineOrchestrator.run_pipeline,
            job_id=job_id,
            job_dir=job_dir,
            pdf_path=pdf_dest,
            session_factory=SessionFactory,
            custom_instructions=effective_instructions,
            score_hints=preflight_hints
        )

    return {
        "job_id": job_id,
        "filename": file.filename,
        "status": initial_status,
        "stage_message": initial_msg,
        "title": final_title,
        "composer": final_composer,
        "page_count": page_count,
        "preflight": preflight_hints,
        "score_hints": preflight_hints,
        "message": "Pre-flight scan ready. Please review AI helps and confirm to process." if not auto_start else "Job created. Use GET /api/v1/jobs/{job_id} or SSE /events to track progress."
    }


@router.get("/api/v1/jobs/{job_id}/preflight")
async def get_job_preflight(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    pdf_file = Path(job.pdf_path)
    if not pdf_file.exists():
        raise HTTPException(status_code=404, detail="Job PDF file missing from disk")

    from services.pdf_layout_svc.layout_engine import PDFLayoutEngine
    try:
        preflight_data = PDFLayoutEngine.preflight_analysis(pdf_file)
        preflight_data["job_id"] = job_id
        return preflight_data
    except Exception as e:
        logger.exception(f"Pre-flight analysis failed for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/jobs/{job_id}/start_processing")
@router.post("/api/v1/jobs/{job_id}/reprocess")
async def reprocess_job_with_hints(
    job_id: str,
    hints: ScoreHintsRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = STORAGE_DIR / "jobs" / job_id
    pdf_dest = Path(job.pdf_path)
    if not pdf_dest.exists():
        raise HTTPException(status_code=404, detail="Job PDF file missing from storage")

    # Clean up previous compiled outputs
    compiled_dir = job_dir / "compiled"
    if compiled_dir.exists():
        shutil.rmtree(compiled_dir, ignore_errors=True)

    dump_fn = getattr(hints, "model_dump", getattr(hints, "dict"))
    hints_dict = dump_fn(exclude_none=True)
    is_initial_start = (job.status == "awaiting_verification")

    job.status = "pending"
    job.stage_message = (
        "User verified AI helps. Starting pipeline processing..."
        if is_initial_start
        else "Reprocessing score with user AI hints..."
    )
    job.error_message = None
    job.score_hints = hints_dict
    db.commit()

    # Record teacher signal in learning store for continuous adaptation
    if hints.save_as_template is not False:
        try:
            from common.learning_store import LearningManager
            LearningManager.record_teacher_signal(
                job_id=job_id,
                title=job.title or "Choral Score",
                composer=job.composer or "Unknown Composer",
                score_hints=hints_dict,
                layout_data=job.layout_data,
                cism=job.raw_cism
            )
            logger.info(f"Recorded teacher signal for job {job_id} into learning store.")
        except Exception as e:
            logger.warning(f"Failed to record teacher signal for job {job_id}: {e}")

    background_tasks.add_task(
        PipelineOrchestrator.run_pipeline,
        job_id=job_id,
        job_dir=job_dir,
        pdf_path=pdf_dest,
        session_factory=SessionFactory,
        custom_instructions=hints.custom_instructions,
        score_hints=hints_dict
    )

    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Score reprocessing initiated with AI helps.",
        "score_hints": hints_dict
    }


@router.get("/api/v1/jobs/{job_id}")
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job.id,
        "status": job.status,
        "stage_message": job.stage_message,
        "title": job.title,
        "composer": job.composer,
        "page_count": job.page_count,
        "total_measures": job.total_measures,
        "total_duration_seconds": job.total_duration_seconds,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "layout_data": job.layout_data,
        "raw_cism": job.raw_cism,
        "routed_cism": job.routed_cism,
        "decoder_result": job.decoder_result,
        "overrides": job.overrides,
        "score_hints": job.score_hints,
        "verification_report": job.verification_report,
        "error_message": job.error_message,
    }


@router.get("/api/v1/jobs/{job_id}/events")
async def job_events_sse(job_id: str):
    """Server-Sent Events stream for real-time stepper updates in the Diagnostic UI."""
    async def event_generator():
        last_status = None
        last_stage_msg = None
        for _ in range(300):  # Stream up to 5 minutes
            db = SessionFactory()
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                db.close()
                yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
                break

            curr_status = job.status
            curr_stage = job.stage_message
            if curr_status != last_status or curr_stage != last_stage_msg:
                payload = {
                    "job_id": job.id,
                    "status": job.status,
                    "stage_message": job.stage_message,
                    "total_measures": job.total_measures,
                    "error_message": job.error_message,
                }
                yield f"data: {json.dumps(payload)}\n\n"
                last_status = curr_status
                last_stage_msg = curr_stage

            db.close()
            if curr_status in ("completed", "failed"):
                break
            await asyncio.sleep(0.8)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/api/v1/jobs/{job_id}/logs")
def get_job_logs(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = STORAGE_DIR / "jobs" / job_id
    log_file = job_dir / "pipeline_telemetry.jsonl"
    logs = []
    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        logs.append(json.loads(line))
        except Exception as e:
            logger.warning(f"Error reading job logs for {job_id}: {e}")

    return {
        "job_id": job_id,
        "status": job.status,
        "stage_message": job.stage_message,
        "error_message": job.error_message,
        "logs": logs,
    }


@router.post("/api/v1/jobs/{job_id}/override")
async def override_voice_routing(
    job_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Applies instant measure-level voice routing overrides without re-running OMR."""
    job_dir = STORAGE_DIR / "jobs" / job_id
    try:
        updated = await PipelineOrchestrator.apply_overrides(
            job_id=job_id,
            job_dir=job_dir,
            overrides=payload.get("overrides", {}),
            session_factory=SessionFactory
        )
        return {"status": "success", "result": updated}
    except Exception as e:
        logger.exception(f"Override failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/jobs/{job_id}/files/{file_subpath:path}")
def serve_job_file(job_id: str, file_subpath: str):
    file_path = STORAGE_DIR / "jobs" / job_id / file_subpath
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Requested file not found")

    ext = file_path.suffix.lower()
    media_map = {
        ".png": "image/png",
        ".pdf": "application/pdf",
        ".json": "application/json",
        ".musicxml": "application/vnd.recordare.musicxml+xml",
        ".xml": "application/xml",
        ".mid": "audio/midi",
        ".midi": "audio/midi",
        ".mp3": "audio/mpeg",
    }
    return FileResponse(file_path, media_type=media_map.get(ext, "application/octet-stream"))


@router.get("/api/v1/jobs/{job_id}/piano_musicxml")
def get_piano_musicxml(job_id: str):
    file_path = STORAGE_DIR / "jobs" / job_id / "compiled" / "score_piano.musicxml"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="score_piano.musicxml not found for this job")
    return FileResponse(file_path, media_type="application/vnd.recordare.musicxml+xml", filename=f"{job_id}_piano.musicxml")


@router.get("/api/v1/jobs/{job_id}/vocals_musicxml")
def get_vocals_musicxml(job_id: str):
    file_path = STORAGE_DIR / "jobs" / job_id / "compiled" / "score_vocals.musicxml"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="score_vocals.musicxml not found for this job")
    return FileResponse(file_path, media_type="application/vnd.recordare.musicxml+xml", filename=f"{job_id}_vocals.musicxml")


@router.get("/api/v1/jobs/{job_id}/score_musicxml")
def get_score_musicxml(job_id: str):
    file_path = STORAGE_DIR / "jobs" / job_id / "compiled" / "score.musicxml"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="score.musicxml not found for this job")
    return FileResponse(file_path, media_type="application/vnd.recordare.musicxml+xml", filename=f"{job_id}_score.musicxml")


@router.get("/api/v1/jobs")
def list_jobs(limit: int = 10, db: Session = Depends(get_db)):
    """Returns the most recent jobs submitted (up to limit, defaults to 10) with full metadata and score hints."""
    effective_limit = max(1, min(limit, 50))
    jobs = db.query(Job).order_by(Job.created_at.desc()).limit(effective_limit).all()
    return [
        {
            "job_id": j.id,
            "filename": j.original_filename,
            "title": j.title,
            "composer": j.composer,
            "status": j.status,
            "stage_message": j.stage_message,
            "page_count": j.page_count,
            "total_measures": j.total_measures,
            "total_duration_seconds": j.total_duration_seconds,
            "score_hints": j.score_hints,
            "verification_report": j.verification_report,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "updated_at": j.updated_at.isoformat() if j.updated_at else None,
        }
        for j in jobs
    ]



@router.get("/api/v1/learning/blueprints")
def get_learned_blueprints():
    """Returns all learned score style blueprints and their fingerprints."""
    from common.learning_store import LearningManager
    try:
        bps = LearningManager.load_all_blueprints()
        return {k: v.model_dump() for k, v in bps.items()}
    except Exception as e:
        logger.warning(f"Error fetching learned blueprints: {e}")
        return {}


app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
