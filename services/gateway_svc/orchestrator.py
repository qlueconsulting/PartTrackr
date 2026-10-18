import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional
import httpx
from sqlalchemy.orm import Session

from services.gateway_svc.database import Job

logger = logging.getLogger("gateway_svc.orchestrator")

LAYOUT_SVC_URL = os.environ.get("LAYOUT_SVC_URL", "http://localhost:8006")
OMR_SVC_URL = os.environ.get("OMR_SVC_URL", "http://localhost:8007")
ROUTER_SVC_URL = os.environ.get("ROUTER_SVC_URL", "http://localhost:8008")
DECODER_SVC_URL = os.environ.get("DECODER_SVC_URL", "http://localhost:8009")


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

        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                # Stage 1: Layout & Crops
                job.status = "layout"
                job.stage_message = "Rasterizing PDF at 300 DPI and detecting staff bounding boxes..."
                db.commit()

                layout_payload = {
                    "job_id": job_id,
                    "pdf_path": str(pdf_path),
                    "output_dir": str(job_dir / "layout"),
                    "dpi": 300,
                }
                resp_layout = await client.post(f"{LAYOUT_SVC_URL}/api/v1/layout/process", json=layout_payload)
                if resp_layout.status_code != 200:
                    raise RuntimeError(f"Layout service error: {resp_layout.text}")
                layout_data = resp_layout.json()

                job.layout_data = layout_data
                job.title = layout_data.get("title", job.title)
                job.composer = layout_data.get("composer", job.composer)
                job.page_count = layout_data.get("page_count", 1)
                db.commit()

                # Stage 2: OMR AI Recognition
                job.status = "omr"
                job.stage_message = "Extracting symbolic musical elements and lyrics into Raw CISM JSON..."
                db.commit()

                omr_payload = {
                    "job_id": job_id,
                    "pdf_path": str(pdf_path),
                    "layout_data": layout_data,
                    "custom_instructions": custom_instructions,
                }
                resp_omr = await client.post(f"{OMR_SVC_URL}/api/v1/omr/process", json=omr_payload)
                if resp_omr.status_code != 200:
                    raise RuntimeError(f"OMR service error: {resp_omr.text}")
                raw_cism = resp_omr.json()

                job.raw_cism = raw_cism
                db.commit()

                # Stage 3: Dynamic Voice Routing (11 Parts)
                job.status = "routing"
                job.stage_message = "Routing staves to 11 canonical tracks with unison duplication & divisi splitting..."
                db.commit()

                router_payload = {
                    "job_id": job_id,
                    "cism": raw_cism,
                    "overrides": job.overrides,
                }
                resp_router = await client.post(f"{ROUTER_SVC_URL}/api/v1/router/process", json=router_payload)
                if resp_router.status_code != 200:
                    raise RuntimeError(f"Voice router service error: {resp_router.text}")
                routed_cism = resp_router.json()

                job.routed_cism = routed_cism
                db.commit()

                # Stage 4: Decoding, MusicXML, MIDI, & Sync Map
                job.status = "decoding"
                job.stage_message = "Compiling validated MusicXML, 11-channel MIDI, and synchronization map..."
                db.commit()

                decoder_payload = {
                    "job_id": job_id,
                    "cism": routed_cism,
                    "output_dir": str(job_dir / "compiled"),
                }
                resp_decoder = await client.post(f"{DECODER_SVC_URL}/api/v1/decoder/compile", json=decoder_payload)
                if resp_decoder.status_code != 200:
                    raise RuntimeError(f"Decoder service error: {resp_decoder.text}")
                decoder_result = resp_decoder.json()

                job.status = "completed"
                job.stage_message = "Pipeline processing completed successfully."
                job.decoder_result = decoder_result
                job.total_measures = decoder_result.get("total_measures", 0)
                job.total_duration_seconds = decoder_result.get("total_duration_seconds", 0.0)
                db.commit()

            except Exception as e:
                logger.exception(f"Pipeline error on job {job_id}: {e}")
                job.status = "failed"
                job.stage_message = f"Failed at {job.status} stage"
                job.error_message = str(e)
                db.commit()
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

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                # Re-route
                resp_router = await client.post(f"{ROUTER_SVC_URL}/api/v1/router/process", json={
                    "job_id": job_id,
                    "cism": job.raw_cism,
                    "overrides": overrides
                })
                routed_cism = resp_router.json()
                job.routed_cism = routed_cism

                # Re-compile
                resp_decoder = await client.post(f"{DECODER_SVC_URL}/api/v1/decoder/compile", json={
                    "job_id": job_id,
                    "cism": routed_cism,
                    "output_dir": str(job_dir / "compiled"),
                })
                decoder_res = resp_decoder.json()
                job.decoder_result = decoder_res
                db.commit()
                return {
                    "routed_cism": routed_cism,
                    "decoder_result": decoder_res,
                }
            finally:
                db.close()
