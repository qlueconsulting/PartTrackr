import logging
import os
from pathlib import Path
import traceback
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from common.cism_schema import ScoreCISM
from services.omr_ai_svc.vector_smufl_extractor import VectorSMuFLExtractor
from services.omr_ai_svc.vision_llm_adapter import VisionLLMAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("omr_ai_svc")

app = FastAPI(
    title="PartTrackr - OMR AI Service",
    version="1.0.0",
    description="Hybrid Choral OMR: Deterministic SMuFL Vector Extractor + Vision-LLM Adapter -> Raw CISM JSON",
)


class OMRRequest(BaseModel):
    job_id: str
    pdf_path: str
    layout_data: Dict[str, Any]
    custom_instructions: Optional[str] = None
    score_hints: Optional[Dict[str, Any]] = None
    gemini_api_key: Optional[str] = None


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "omr-ai-svc",
        "port": 8007,
        "gemini_configured": bool(os.environ.get("GEMINI_API_KEY")),
        "ollama_base_url": os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434"),
    }


@app.post("/api/v1/omr/process", response_model=ScoreCISM)
def process_omr(req: OMRRequest) -> ScoreCISM:
    pdf_file = Path(req.pdf_path)
    if not pdf_file.exists():
        raise HTTPException(status_code=404, detail=f"PDF file not found at {req.pdf_path}")

    custom_instr = req.custom_instructions or (req.score_hints.get("custom_instructions") if req.score_hints else None)

    try:
        # 1. Deterministic Fast Path: Vector SMuFL extraction for digital PDFs
        if VectorSMuFLExtractor.can_extract(pdf_file):
            logger.info(f"Job {req.job_id}: Detected SMuFL vector glyphs in {pdf_file.name}. Running direct vector extraction...")
            score_cism = VectorSMuFLExtractor.extract_cism(pdf_file, req.layout_data, score_hints=req.score_hints)
            return score_cism

        # 2. Blended Neuro-Symbolic OMR: Fused OCR + Morphological Geometric OMR + Music Theory + Vision-LLM
        logger.info(f"Job {req.job_id}: Running Blended Sensor-Fusion OMR (OCR + Geometric OMR + Music Theory) on {pdf_file.name}...")
        from services.omr_ai_svc.hybrid_fusion_engine import HybridOMRFusionEngine
        score_cism = HybridOMRFusionEngine.extract_cism(
            layout_data=req.layout_data,
            custom_instructions=custom_instr,
            score_hints=req.score_hints,
            gemini_api_key=req.gemini_api_key
        )
        return score_cism

    except Exception as e:
        tb = traceback.format_exc()
        logger.exception(f"OMR processing failed for job {req.job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"OMR processing error: {str(e)}\n\nTraceback:\n{tb}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8007)
