import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
from typing import Optional, Dict, Any, List
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
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


@app.post("/api/v1/jobs/upload")
async def upload_pdf_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    custom_instructions: Optional[str] = Form(None),
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

    job = Job(
        id=job_id,
        original_filename=file.filename,
        pdf_path=str(pdf_dest),
        title=Path(file.filename).stem.replace("_", " ").title(),
        status="pending",
        stage_message="File uploaded, initializing pipeline..."
    )
    db.add(job)
    db.commit()

    # Trigger async pipeline
    background_tasks.add_task(
        PipelineOrchestrator.run_pipeline,
        job_id=job_id,
        job_dir=job_dir,
        pdf_path=pdf_dest,
        session_factory=SessionFactory,
        custom_instructions=custom_instructions
    )

    return {
        "job_id": job_id,
        "filename": file.filename,
        "status": "pending",
        "message": "Job created. Use GET /api/v1/jobs/{job_id} or SSE /events to track progress."
    }


@app.get("/api/v1/jobs/{job_id}")
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
        "error_message": job.error_message,
    }


@app.get("/api/v1/jobs/{job_id}/events")
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
                }
                yield f"data: {json.dumps(payload)}\n\n"
                last_status = curr_status
                last_stage_msg = curr_stage

            db.close()
            if curr_status in ("completed", "failed"):
                break
            await asyncio.sleep(0.8)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/v1/jobs/{job_id}/override")
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


@app.get("/api/v1/jobs/{job_id}/files/{file_subpath:path}")
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


@app.get("/api/v1/jobs")
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.created_at.desc()).limit(30).all()
    return [
        {
            "job_id": j.id,
            "filename": j.original_filename,
            "title": j.title,
            "status": j.status,
            "stage_message": j.stage_message,
            "total_measures": j.total_measures,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        }
        for j in jobs
    ]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
