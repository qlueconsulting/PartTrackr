import asyncio
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import traceback
from typing import Dict, Any, Optional
import uuid
import httpx
from sqlalchemy.orm import Session

from services.gateway_svc.database import Job

logger = logging.getLogger("gateway_svc.orchestrator")

LAYOUT_SVC_URL = os.environ.get("LAYOUT_SVC_URL", "http://localhost:8006")
OMR_SVC_URL = os.environ.get("OMR_SVC_URL", "http://localhost:8007")
ROUTER_SVC_URL = os.environ.get("ROUTER_SVC_URL", "http://localhost:8008")
DECODER_SVC_URL = os.environ.get("DECODER_SVC_URL", "http://localhost:8009")


def append_job_log(job_dir: Path, level: str, service: str, message: str, details: Any = None):
    log_file = job_dir / "pipeline_telemetry.jsonl"
    entry = {
        "id": f"{int(datetime.utcnow().timestamp() * 1000)}-{uuid.uuid4().hex[:4]}",
        "timestamp": datetime.utcnow().strftime("%H:%M:%S"),
        "level": level,
        "service": service,
        "message": message,
        "details": details,
    }
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning(f"Could not append to job log: {e}")


class PipelineOrchestrator:
    """
    Coordinates execution of the 4 microservices across the shared storage volume:
    1. pdf-layout-svc: 300 DPI rendering and bounding box crops
    2. omr-ai-svc: Raw CISM JSON extraction
    3. voice-router-svc: 11-part canonical mapping
    4. decoder-xml-svc: MusicXML, MIDI, and sync map compilation
    """

    @classmethod
    async def run_pipeline(
        cls,
        job_id: str,
        job_dir: Path,
        pdf_path: Path,
        session_factory,
        custom_instructions: Optional[str] = None
    ):
        db: Session = session_factory()
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            db.close()
            return

        append_job_log(job_dir, "info", "gateway-svc", f"Pipeline initiated for '{pdf_path.name}' (Job ID: {job_id})")

        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                # Stage 1: Layout & Crops
                job.status = "layout"
                job.stage_message = "Rasterizing PDF at 300 DPI and detecting staff bounding boxes..."
                db.commit()

                append_job_log(
                    job_dir, "info", "pdf-layout-svc",
                    f"POST {LAYOUT_SVC_URL}/api/v1/layout/process - Rasterizing pages and extracting staves..."
                )

                layout_payload = {
                    "job_id": job_id,
                    "pdf_path": str(pdf_path),
                    "output_dir": str(job_dir / "layout"),
                    "dpi": 300,
                }
                resp_layout = await client.post(f"{LAYOUT_SVC_URL}/api/v1/layout/process", json=layout_payload)
                if resp_layout.status_code != 200:
                    err_txt = resp_layout.text
                    append_job_log(job_dir, "error", "pdf-layout-svc", f"Layout service error HTTP {resp_layout.status_code}", err_txt)
                    raise RuntimeError(f"Layout service error: {err_txt}")

                layout_data = resp_layout.json()
                job.layout_data = layout_data
                job.title = layout_data.get("title", job.title)
                job.composer = layout_data.get("composer", job.composer)
                job.page_count = layout_data.get("page_count", 1)
                db.commit()

                append_job_log(
                    job_dir, "success", "pdf-layout-svc",
                    f"Layout complete: Title='{job.title}', Composer='{job.composer}', Pages={job.page_count}, Systems={layout_data.get('total_systems')}, Measures={layout_data.get('total_measures')}",
                    {
                        "title": job.title,
                        "composer": job.composer,
                        "page_count": job.page_count,
                        "total_systems": layout_data.get("total_systems"),
                        "total_measures": layout_data.get("total_measures"),
                        "has_piano": layout_data.get("has_piano"),
                    }
                )

                # Stage 2: OMR AI Recognition
                job.status = "omr"
                job.stage_message = "Extracting symbolic musical elements and lyrics into Raw CISM JSON..."
                db.commit()

                append_job_log(
                    job_dir, "info", "omr-ai-svc",
                    f"POST {OMR_SVC_URL}/api/v1/omr/process - Running hybrid OMR across {layout_data.get('total_systems')} systems..."
                )

                omr_payload = {
                    "job_id": job_id,
                    "pdf_path": str(pdf_path),
                    "layout_data": layout_data,
                    "custom_instructions": custom_instructions,
                }
                resp_omr = await client.post(f"{OMR_SVC_URL}/api/v1/omr/process", json=omr_payload)
                if resp_omr.status_code != 200:
                    err_txt = resp_omr.text
                    append_job_log(job_dir, "error", "omr-ai-svc", f"OMR service error HTTP {resp_omr.status_code}", err_txt)
                    raise RuntimeError(f"OMR service error: {err_txt}")

                raw_cism = resp_omr.json()
                job.raw_cism = raw_cism
                db.commit()

                engine_used = raw_cism.get("metadata", {}).get("omr_engine", "OMR")
                append_job_log(
                    job_dir, "success", "omr-ai-svc",
                    f"OMR complete [{engine_used}]: Extracted {raw_cism.get('total_measures')} measures into Raw CISM JSON",
                    {"total_measures": raw_cism.get("total_measures"), "engine": engine_used}
                )

                # Stage 3: Dynamic Voice Routing (11 Parts)
                job.status = "routing"
                job.stage_message = "Routing staves to 11 canonical tracks with unison duplication & divisi splitting..."
                db.commit()

                append_job_log(
                    job_dir, "info", "voice-router-svc",
                    f"POST {ROUTER_SVC_URL}/api/v1/router/process - Routing staves to 11 canonical tracks..."
                )

                router_payload = {
                    "job_id": job_id,
                    "cism": raw_cism,
                    "overrides": job.overrides,
                }
                resp_router = await client.post(f"{ROUTER_SVC_URL}/api/v1/router/process", json=router_payload)
                if resp_router.status_code != 200:
                    err_txt = resp_router.text
                    append_job_log(job_dir, "error", "voice-router-svc", f"Voice router error HTTP {resp_router.status_code}", err_txt)
                    raise RuntimeError(f"Voice router service error: {err_txt}")

                routed_cism = resp_router.json()
                job.routed_cism = routed_cism
                db.commit()

                append_job_log(
                    job_dir, "success", "voice-router-svc",
                    f"Voice routing complete: 11 canonical tracks routed across {len(routed_cism.get('systems', []))} systems",
                    {"systems": len(routed_cism.get("systems", []))}
                )

                # Stage 4: Decoding, MusicXML, MIDI, & Sync Map
                job.status = "decoding"
                job.stage_message = "Compiling validated MusicXML, 11-channel MIDI, and synchronization map..."
                db.commit()

                append_job_log(
                    job_dir, "info", "decoder-xml-svc",
                    f"POST {DECODER_SVC_URL}/api/v1/decoder/compile - Validating metric lockstep, MusicXML, and MIDI..."
                )

                decoder_payload = {
                    "job_id": job_id,
                    "cism": routed_cism,
                    "output_dir": str(job_dir / "compiled"),
                }
                resp_decoder = await client.post(f"{DECODER_SVC_URL}/api/v1/decoder/compile", json=decoder_payload)
                if resp_decoder.status_code != 200:
                    err_txt = resp_decoder.text
                    append_job_log(job_dir, "error", "decoder-xml-svc", f"Decoder error HTTP {resp_decoder.status_code}", err_txt)
                    raise RuntimeError(f"Decoder service error: {err_txt}")

                decoder_result = resp_decoder.json()

                job.status = "completed"
                job.stage_message = "Pipeline processing completed successfully."
                job.decoder_result = decoder_result
                job.total_measures = decoder_result.get("total_measures", 0)
                job.total_duration_seconds = decoder_result.get("total_duration_seconds", 0.0)
                job.error_message = None
                db.commit()

                append_job_log(
                    job_dir, "success", "decoder-xml-svc",
                    f"Compilation complete: {job.total_measures} measures validated, {job.total_duration_seconds:.1f}s duration. MusicXML & 11-channel MIDI ready.",
                    {
                        "total_measures": job.total_measures,
                        "total_duration_seconds": job.total_duration_seconds,
                        "musicxml": decoder_result.get("score_musicxml_path"),
                        "midi": decoder_result.get("score_midi_path"),
                        "sync_map": decoder_result.get("sync_map_path"),
                    }
                )

            except Exception as e:
                err_str = str(e)
                full_tb = traceback.format_exc()
                failed_stage = job.status if job.status != "pending" else "initialization"
                logger.exception(f"Pipeline error on job {job_id}: {err_str}")
                job.status = "failed"
                job.stage_message = f"Failed at {failed_stage} stage: {err_str[:120]}"
                job.error_message = err_str
                db.commit()

                append_job_log(
                    job_dir, "error", "gateway-svc",
                    f"Pipeline failed at '{failed_stage}' stage: {err_str}",
                    {"stage": failed_stage, "error_details": err_str, "traceback": full_tb}
                )
            finally:
                db.close()

    @classmethod
    async def apply_overrides(
        cls,
        job_id: str,
        job_dir: Path,
        overrides: Dict[str, Any],
        session_factory
    ) -> Dict[str, Any]:
        """Fast re-routing and compilation without re-running OMR."""
        db: Session = session_factory()
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or not job.raw_cism:
            db.close()
            raise ValueError("Job or Raw CISM data not found")

        job.overrides = overrides
        db.commit()

        append_job_log(job_dir, "info", "voice-router-svc", f"Applying measure overrides for {len(overrides)} measure(s)...", overrides)

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                # Re-route
                resp_router = await client.post(f"{ROUTER_SVC_URL}/api/v1/router/process", json={
                    "job_id": job_id,
                    "cism": job.raw_cism,
                    "overrides": overrides
                })
                if resp_router.status_code != 200:
                    raise RuntimeError(f"Router service error: {resp_router.text}")
                routed_cism = resp_router.json()
                job.routed_cism = routed_cism

                # Re-compile
                resp_decoder = await client.post(f"{DECODER_SVC_URL}/api/v1/decoder/compile", json={
                    "job_id": job_id,
                    "cism": routed_cism,
                    "output_dir": str(job_dir / "compiled"),
                })
                if resp_decoder.status_code != 200:
                    raise RuntimeError(f"Decoder service error: {resp_decoder.text}")
                decoder_result = resp_decoder.json()

                job.decoder_result = decoder_result
                job.total_measures = decoder_result.get("total_measures", job.total_measures)
                job.total_duration_seconds = decoder_result.get("total_duration_seconds", job.total_duration_seconds)
                db.commit()

                append_job_log(job_dir, "success", "voice-router-svc", "Overrides re-compiled and synchronized successfully.")

                return {
                    "routed_cism": routed_cism,
                    "decoder_result": decoder_result,
                }
            except Exception as e:
                append_job_log(job_dir, "error", "gateway-svc", f"Override re-compilation failed: {e}")
                raise
            finally:
                db.close()
