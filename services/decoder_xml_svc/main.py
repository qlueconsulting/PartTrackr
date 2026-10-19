import logging
from pathlib import Path
import traceback
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from common.cism_schema import ScoreCISM
from common.lockstep_utils import reconcile_cism_measures
from services.decoder_xml_svc.xml_compiler import XMLCompiler
from services.decoder_xml_svc.midi_generator import MIDIGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("decoder_xml_svc")

app = FastAPI(
    title="PartTrackr - Decoder XML Service",
    version="1.0.0",
    description="Compiles 11-part CISM JSON into MusicXML, 11-channel MIDI, and synchronization maps",
)


class DecodeRequest(BaseModel):
    job_id: str
    cism: ScoreCISM
    output_dir: str
    score_hints: Optional[Dict[str, Any]] = Field(None, description="Score hints including verified total_measures")


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "decoder-xml-svc", "port": 8009}


@app.post("/api/v1/decoder/compile")
def compile_score(req: DecodeRequest) -> Dict[str, Any]:
    out_dir = Path(req.output_dir)
    try:
        logger.info(f"Compiling MusicXML and MIDI for job {req.job_id}...")

        target_measures = req.score_hints.get("total_measures") if req.score_hints else None
        target_ts = req.score_hints.get("time_signature") if req.score_hints else None
        target_bpm = req.score_hints.get("tempo_bpm") if req.score_hints else None
        accompaniment_type = req.score_hints.get("accompaniment_type") if req.score_hints else None

        has_piano = None
        if accompaniment_type == "a_cappella":
            has_piano = False
        elif accompaniment_type in ("piano", "orchestra_reduction"):
            has_piano = True

        cism = req.cism
        if target_measures:
            cism = reconcile_cism_measures(
                cism,
                target_total_measures=int(target_measures),
                target_time_signature=target_ts,
                target_tempo_bpm=target_bpm,
                has_piano=has_piano
            )
        elif has_piano is not None:
            cism.has_piano = has_piano

        # 1. Compile MusicXML and individual stems
        main_xml_path, stem_xml_paths, measure_summary = XMLCompiler.compile_score(
            cism=cism,
            output_dir=out_dir
        )

        # 2. Compile 11-channel MIDI, individual stem MIDIs, and sync map
        main_midi_path, stem_midi_paths, sync_map_path = MIDIGenerator.compile_midi_and_sync_map(
            cism=cism,
            output_dir=out_dir
        )

        stems_manifest = {}
        for p_name in stem_xml_paths:
            stems_manifest[p_name] = {
                "musicxml_path": str(stem_xml_paths[p_name]),
                "midi_path": str(stem_midi_paths.get(p_name, "")),
            }

        return {
            "job_id": req.job_id,
            "status": "completed",
            "score_musicxml_path": str(main_xml_path),
            "score_midi_path": str(main_midi_path),
            "sync_map_path": str(sync_map_path),
            "stems": stems_manifest,
            "measure_summary": measure_summary,
            "total_measures": target_measures if target_measures else len(measure_summary),
            "total_duration_seconds": measure_summary[-1]["start_time_seconds"] + measure_summary[-1]["duration_seconds"] if measure_summary else 0.0,
        }

    except Exception as e:
        tb = traceback.format_exc()
        logger.exception(f"Decoder compilation failed for job {req.job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Compilation error: {str(e)}\n\nTraceback:\n{tb}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8009)
