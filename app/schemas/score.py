from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class StemInfo(BaseModel):
    name: str # e.g. "Piano", "S1", "S2", "A1", "A2", "T1", "T2", "Bar1", "Bar2", "B1", "B2"
    display_name: str
    category: str # "accompaniment", "soprano", "alto", "tenor", "baritone", "bass"
    audio_url: str
    musicxml_url: str
    midi_url: str
    note_count: int = 0
    is_active_in_score: bool = True
    default_pan: float = 0.0 # -1.0 to 1.0

class MeasureInfo(BaseModel):
    measure_number: int
    start_time_seconds: float
    duration_seconds: float
    quarter_length: float
    time_signature: str
    tempo_bpm: float
    active_parts: List[str] = Field(default_factory=list)
    resting_parts: List[str] = Field(default_factory=list)
    entrances: List[str] = Field(default_factory=list)

class AuditCheckItem(BaseModel):
    name: str
    passed: bool
    score_pct: float
    details: str

class AuditReport(BaseModel):
    overall_match_integrity_pct: float
    accompaniment_continuity: bool
    vocal_line_recovery_pct: float
    interlude_cleanliness_pct: float
    measure_lockstep_verified: bool
    measure_count: int
    time_drift_max_seconds: float
    checks: List[AuditCheckItem] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)

class ScoreResponse(BaseModel):
    id: str
    title: str
    composer: str
    original_filename: str
    file_type: str
    status: str
    status_message: Optional[str] = None
    created_at: datetime
    measure_count: int
    total_duration_seconds: float
    time_signature: str
    tempo_bpm: float
    stems: Dict[str, StemInfo] = Field(default_factory=dict)
    analysis: List[MeasureInfo] = Field(default_factory=list)
    audit: Optional[AuditReport] = None

class ScoreSummary(BaseModel):
    id: str
    title: str
    composer: str
    original_filename: str
    file_type: str
    status: str
    created_at: datetime
    measure_count: int
    total_duration_seconds: float
    active_stems_count: int
