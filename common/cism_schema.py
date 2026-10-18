from __future__ import annotations
from typing import List, Dict, Optional, Any, Union
from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x: float = Field(..., description="Left X coordinate in points or normalized pixels")
    y: float = Field(..., description="Top Y coordinate in points or normalized pixels")
    w: float = Field(..., description="Width")
    h: float = Field(..., description="Height")


class NoteElement(BaseModel):
    pitch: Optional[str] = Field(None, description="Scientific pitch notation e.g. C4, G#5, Bb3, or None if rest")
    midi_pitch: Optional[int] = Field(None, description="MIDI note number (e.g. 60 for Middle C)")
    duration_quarters: float = Field(..., description="Duration in quarter-note lengths (e.g. 1.0 = quarter, 0.5 = eighth)")
    duration_type: str = Field("quarter", description="Note duration type name: whole, half, quarter, eighth, 16th, etc.")
    offset_quarters: float = Field(0.0, description="Offset from measure start in quarter lengths")
    stem_direction: Optional[str] = Field(None, description="'up', 'down', or None")
    is_rest: bool = Field(False, description="True if this is a rest")
    is_chord: bool = Field(False, description="True if multiple pitches sound together")
    chord_pitches: List[str] = Field(default_factory=list, description="Pitches if chord")
    lyric: Optional[str] = Field(None, description="Underlying lyric text or syllable")
    tie: Optional[str] = Field(None, description="'start', 'stop', or 'continue'")
    accidental: Optional[str] = Field(None, description="'#', 'b', 'natural', etc.")
    bounding_box: Optional[BoundingBox] = None


class TrackData(BaseModel):
    track_name: str = Field(..., description="Canonical part name or raw staff identifier")
    clef: str = Field("treble", description="'treble', 'bass', 'tenor', 'alto', 'grand'")
    elements: List[NoteElement] = Field(default_factory=list)


class StaffInfo(BaseModel):
    staff_id: str
    index: int
    clef: str = "treble"
    bracket_type: str = Field("none", description="'bracket' for choir, 'brace' for piano, 'none'")
    role: str = Field("unknown", description="'vocal', 'piano_rh', 'piano_lh', 'unknown'")
    y_top: float
    y_bot: float
    has_lyrics: bool = False
    label: Optional[str] = None


class MeasureData(BaseModel):
    measure_number: int
    time_signature: str = "4/4"
    tempo_bpm: float = 120.0
    key_signature_fifths: int = 0
    quarter_length: float = 4.0
    is_pickup: bool = False
    bounding_box: Optional[BoundingBox] = None
    raw_staves: Dict[str, TrackData] = Field(default_factory=dict, description="Pre-routing raw staves from OMR")
    tracks: Dict[str, TrackData] = Field(default_factory=dict, description="11 canonical routed tracks")


class SystemData(BaseModel):
    system_index: int
    page_num: int
    bounding_box: BoundingBox
    staves: List[StaffInfo] = Field(default_factory=list)
    measures: List[MeasureData] = Field(default_factory=list)


class ScoreCISM(BaseModel):
    score_id: str
    title: str
    composer: str = "Unknown Composer"
    subtitle: Optional[str] = None
    page_count: int = 1
    total_systems: int = 1
    total_measures: int = 0
    has_piano: bool = False
    systems: List[SystemData] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_measure(self, measure_number: int) -> Optional[MeasureData]:
        for sys in self.systems:
            for m in sys.measures:
                if m.measure_number == measure_number:
                    return m
        return None

    def all_measures(self) -> List[MeasureData]:
        res = []
        for sys in self.systems:
            res.extend(sys.measures)
        return res
