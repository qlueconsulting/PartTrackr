import logging
import traceback
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from common.cism_schema import ScoreCISM
from services.voice_router_svc.router_engine import VoiceRouterEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("voice_router_svc")

app = FastAPI(
    title="PartTrackr - Voice Router Service",
    version="1.0.0",
    description="Maps Raw CISM JSON staves into 11 canonical tracks with unison duplication & divisi splitting",
)


class RouteRequest(BaseModel):
    job_id: str
    cism: ScoreCISM
    overrides: Optional[Dict[str, Any]] = Field(None, description="Manual measure-level voice routing overrides from the UI")
    score_hints: Optional[Dict[str, Any]] = Field(None, description="Score hints including total_measures, accompaniment_type, etc.")


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "voice-router-svc", "port": 8008}


@app.post("/api/v1/router/process", response_model=ScoreCISM)
def route_voices(req: RouteRequest) -> ScoreCISM:
    try:
        logger.info(f"Routing raw staves to 11 canonical parts for job {req.job_id}...")
        routed_cism = VoiceRouterEngine.route_score(req.cism, overrides=req.overrides, score_hints=req.score_hints)
        return routed_cism
    except Exception as e:
        tb = traceback.format_exc()
        logger.exception(f"Voice routing failed for job {req.job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Voice routing error: {str(e)}\n\nTraceback:\n{tb}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8008)
