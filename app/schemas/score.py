from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class StemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    score_id: str
    part_name: str
    part_key: str
    is_accompaniment: bool
    original_part_name: Optional[str] = None
    duration_seconds: float
    pitch_range: Optional[str] = None
    measure_count: int
    note_count: int
    audio_url: str
    midi_url: str


class ScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    title: str
    composer: Optional[str] = None
    status: str
    detected_parts: List[str]
    error_message: Optional[str] = None
    error_traceback: Optional[str] = None
    processing_logs: List[Dict[str, Any]] = []
    measure_analysis: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    stems: List[StemResponse] = []
    xml_url: Optional[str] = None
    pdf_url: Optional[str] = None


class ScoreListResponse(BaseModel):
    scores: List[ScoreResponse]
    total: int
