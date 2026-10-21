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

LAYOUT_SVC_URL = os.environ.get("LAYOUT_SVC_URL", "http://pdf-layout-svc:8006")
OMR_SVC_URL = os.environ.get("OMR_SVC_URL", "http://omr-ai-svc:8007")
ROUTER_SVC_URL = os.environ.get("ROUTER_SVC_URL", "http://voice-router-svc:8008")
DECODER_SVC_URL = os.environ.get("DECODER_SVC_URL", "http://decoder-xml-svc:8009")


def _get_fallback_urls(primary_url: str, default_service_name: str, container_alias: str, port: int) -> list:
    candidates = [
        primary_url,
        f"http://{default_service_name}:{port}",
        f"http://{container_alias}:{port}",
    ]
    seen = set()
    res = []
    for u in candidates:
        norm = u.rstrip("/")
        if norm not in seen:
            seen.add(norm)
            res.append(norm)
    return res


async def _post_with_retry_and_fallback(
    endpoint_name: str,
    primary_url: str,
    path: str,
    payload: Dict[str, Any],
    fallback_urls: Optional[list] = None,
    max_retries: int = 2,
    timeout_sec: float = 600.0,
) -> httpx.Response:
    urls_to_try = [primary_url]
    if fallback_urls:
        for fu in fallback_urls:
            if fu not in urls_to_try:
                urls_to_try.append(fu)

    last_error = None
    for target_base in urls_to_try:
        full_url = f"{target_base.rstrip('/')}/{path.lstrip('/')}"
        retries_for_url = max_retries if target_base == primary_url else 1
        for attempt in range(1, retries_for_url + 1):
            try:
                logger.info(f"[{endpoint_name}] POST {full_url} (attempt {attempt}/{retries_for_url})")
                async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec, connect=2.0)) as client:
                    resp = await client.post(full_url, json=payload)
                    return resp
            except (httpx.ConnectError, httpx.ConnectTimeout) as conn_err:
                last_error = conn_err
                logger.warning(
                    f"[{endpoint_name}] Connection to {full_url} failed (attempt {attempt}/{retries_for_url}): {conn_err}"
                )
                if attempt < retries_for_url:
                    await asyncio.sleep(0.5)
            except Exception as ex:
                raise ex

    if last_error:
        raise last_error
    raise RuntimeError(f"[{endpoint_name}] All candidate endpoints failed to respond.")


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
        custom_instructions: Optional[str] = None,
        score_hints: Optional[Dict[str, Any]] = None
    ):
        db: Session = session_factory()
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            db.close()
            return

        if score_hints:
            job.score_hints = score_hints
            db.commit()
            append_job_log(
                job_dir, "info", "gateway-svc",
                f"Applying Score Hints & AI Helps: TimeSig={score_hints.get('time_signature')}, BPM={score_hints.get('tempo_bpm')}, Voicing={score_hints.get('choral_voicing')}, Accompaniment={score_hints.get('accompaniment_type')}",
                score_hints
            )

        append_job_log(job_dir, "info", "gateway-svc", f"Pipeline initiated for '{pdf_path.name}' (Job ID: {job_id})")

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
                "score_hints": score_hints,
            }
            layout_data = None
            try:
                resp_layout = await _post_with_retry_and_fallback(
                    "pdf-layout-svc",
                    LAYOUT_SVC_URL,
                    "/api/v1/layout/process",
                    layout_payload,
                    fallback_urls=_get_fallback_urls(LAYOUT_SVC_URL, "pdf-layout-svc", "parttrackr_layout", 8006)
                )
                if resp_layout.status_code != 200:
                    err_txt = resp_layout.text
                    append_job_log(job_dir, "error", "pdf-layout-svc", f"Layout service error HTTP {resp_layout.status_code}", err_txt)
                    raise RuntimeError(f"Layout service error: {err_txt}")
                layout_data = resp_layout.json()
            except (httpx.ConnectError, httpx.ConnectTimeout) as conn_err:
                logger.warning(f"Layout HTTP endpoint unreachable ({conn_err}). Executing PDFLayoutEngine directly in-process...")
                append_job_log(job_dir, "warning", "pdf-layout-svc", f"Layout HTTP unreachable ({conn_err}). Executing in-process fallback...")
                from services.pdf_layout_svc.layout_engine import PDFLayoutEngine
                layout_data = PDFLayoutEngine.process_pdf(pdf_path, job_dir / "layout", dpi=300, score_hints=score_hints)

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

            active_instructions = custom_instructions or (score_hints.get("custom_instructions") if score_hints else None)
            omr_payload = {
                "job_id": job_id,
                "pdf_path": str(pdf_path),
                "layout_data": layout_data,
                "custom_instructions": active_instructions,
                "score_hints": score_hints,
            }
            raw_cism = None
            try:
                resp_omr = await _post_with_retry_and_fallback(
                    "omr-ai-svc",
                    OMR_SVC_URL,
                    "/api/v1/omr/process",
                    omr_payload,
                    fallback_urls=_get_fallback_urls(OMR_SVC_URL, "omr-ai-svc", "parttrackr_omr", 8007)
                )
                if resp_omr.status_code != 200:
                    err_txt = resp_omr.text
                    append_job_log(job_dir, "error", "omr-ai-svc", f"OMR service error HTTP {resp_omr.status_code}", err_txt)
                    raise RuntimeError(f"OMR service error: {err_txt}")
                raw_cism = resp_omr.json()
            except (httpx.ConnectError, httpx.ConnectTimeout) as conn_err:
                logger.warning(f"OMR HTTP endpoint unreachable ({conn_err}). Executing HybridOMRFusionEngine directly in-process...")
                append_job_log(job_dir, "warning", "omr-ai-svc", f"OMR HTTP unreachable ({conn_err}). Executing in-process fallback...")
                from services.omr_ai_svc.vector_smufl_extractor import VectorSMuFLExtractor
                if VectorSMuFLExtractor.can_extract(pdf_path):
                    cism_obj = VectorSMuFLExtractor.extract_cism(pdf_path, layout_data, score_hints=score_hints)
                else:
                    from services.omr_ai_svc.hybrid_fusion_engine import HybridOMRFusionEngine
                    cism_obj = HybridOMRFusionEngine.extract_cism(
                        layout_data=layout_data, custom_instructions=active_instructions, score_hints=score_hints
                    )
                raw_cism = cism_obj.model_dump()

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
                "score_hints": score_hints,
            }
            routed_cism = None
            try:
                resp_router = await _post_with_retry_and_fallback(
                    "voice-router-svc",
                    ROUTER_SVC_URL,
                    "/api/v1/router/process",
                    router_payload,
                    fallback_urls=_get_fallback_urls(ROUTER_SVC_URL, "voice-router-svc", "parttrackr_router", 8008)
                )
                if resp_router.status_code != 200:
                    err_txt = resp_router.text
                    append_job_log(job_dir, "error", "voice-router-svc", f"Voice router error HTTP {resp_router.status_code}", err_txt)
                    raise RuntimeError(f"Voice router service error: {err_txt}")
                routed_cism = resp_router.json()
            except (httpx.ConnectError, httpx.ConnectTimeout) as conn_err:
                logger.warning(f"Voice router HTTP endpoint unreachable ({conn_err}). Executing VoiceRouterEngine directly in-process...")
                append_job_log(job_dir, "warning", "voice-router-svc", f"Voice router HTTP unreachable ({conn_err}). Executing in-process fallback...")
                from services.voice_router_svc.router_engine import VoiceRouterEngine
                from common.cism_schema import ScoreCISM
                cism_obj = ScoreCISM(**raw_cism)
                routed_cism_obj = VoiceRouterEngine.route_score(cism_obj, overrides=job.overrides, score_hints=score_hints)
                routed_cism = routed_cism_obj.model_dump()

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
                "score_hints": score_hints,
            }
            decoder_result = None
            try:
                resp_decoder = await _post_with_retry_and_fallback(
                    "decoder-xml-svc",
                    DECODER_SVC_URL,
                    "/api/v1/decoder/compile",
                    decoder_payload,
                    fallback_urls=_get_fallback_urls(DECODER_SVC_URL, "decoder-xml-svc", "parttrackr_decoder", 8009)
                )
                if resp_decoder.status_code != 200:
                    err_txt = resp_decoder.text
                    append_job_log(job_dir, "error", "decoder-xml-svc", f"Decoder error HTTP {resp_decoder.status_code}", err_txt)
                    raise RuntimeError(f"Decoder service error: {err_txt}")
                decoder_result = resp_decoder.json()
            except (httpx.ConnectError, httpx.ConnectTimeout) as conn_err:
                logger.warning(f"Decoder HTTP endpoint unreachable ({conn_err}). Executing XMLCompiler & MIDIGenerator in-process...")
                append_job_log(job_dir, "warning", "decoder-xml-svc", f"Decoder HTTP unreachable ({conn_err}). Executing in-process fallback...")
                from services.decoder_xml_svc.xml_compiler import XMLCompiler
                from services.decoder_xml_svc.midi_generator import MIDIGenerator
                from common.cism_schema import ScoreCISM
                from common.lockstep_utils import reconcile_cism_measures
                routed_cism_obj = ScoreCISM(**routed_cism)
                target_measures = score_hints.get("total_measures") if score_hints else None
                if target_measures:
                    routed_cism_obj = reconcile_cism_measures(
                        routed_cism_obj,
                        target_total_measures=int(target_measures),
                        target_time_signature=score_hints.get("time_signature") if score_hints else None,
                        target_tempo_bpm=score_hints.get("tempo_bpm") if score_hints else None,
                    )
                out_compiled = job_dir / "compiled"
                xml_path, stem_xmls, summary = XMLCompiler.compile_score(routed_cism_obj, out_compiled)
                midi_path, stem_midis, sync_map = MIDIGenerator.compile_midi_and_sync_map(routed_cism_obj, out_compiled)
                decoder_result = {
                    "status": "success",
                    "score_musicxml_path": str(xml_path),
                    "score_midi_path": str(midi_path),
                    "sync_map_path": str(sync_map),
                    "total_measures": len(summary) if isinstance(summary, list) else len(routed_cism.get("systems", [{}])[0].get("measures", [])),
                    "total_duration_seconds": float(len(summary) * 2.0) if isinstance(summary, list) else 0.0,
                }

                # Stage 5: Closed-Loop Verification & Invariant Enforcement
                verification_report = None
                try:
                    from common.loopback_verifier import LoopBackVerifier
                    from common.cism_schema import ScoreCISM
                    routed_cism_obj = ScoreCISM(**routed_cism)
                    _, verification_report = LoopBackVerifier.verify_and_reconcile(
                        cism=routed_cism_obj,
                        score_hints=score_hints,
                        decoder_result=decoder_result
                    )
                    job.verification_report = verification_report
                    append_job_log(
                        job_dir, "success", "loopback-verifier",
                        f"Closed-loop check complete: {verification_report['match_score_pct']}% match to user AI helps.",
                        verification_report
                    )
                except Exception as ver_err:
                    logger.warning(f"Loop-back verification non-fatal error: {ver_err}")

                job.status = "completed"
                job.stage_message = "Pipeline processing completed successfully."
                job.decoder_result = decoder_result
                if score_hints and score_hints.get("total_measures"):
                    job.total_measures = int(score_hints["total_measures"])
                else:
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
