from __future__ import annotations
import base64
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests

from common.cism_schema import MeasureData, TrackData, NoteElement, BoundingBox
from common.music_theory_engine import MusicTheoryEngine

logger = logging.getLogger("omr_ai_svc.surgical")


class SurgicalMeasureRepair:
    """
    Precision Multimodal AI Micro-Tool for Targeted Measure Repair.
    Rather than processing full pages through LLMs, this tool is ONLY invoked
    on single isolated measures flagged by MusicTheoryEngine as having
    rhythmic or pitch anomalies.
    """

    SURGICAL_PROMPT_TEMPLATE = """You are a precision Optical Music Recognition surgical repair tool.
Analyze ONLY this isolated single measure of sheet music.
Context:
- Clef: {clef}
- Time Signature: {time_signature} (Expected duration: {expected_ql} quarter notes)
- Key Signature: {key_fifths} fifths
- Target Staff: {staff_role}

Inspect the notes, rests, and accidentals in this measure from left to right.
Return ONLY valid JSON matching this schema:
{{
  "notes": [
    {{
      "pitch": "F#4",
      "duration_quarters": 1.0,
      "is_rest": false,
      "stem_direction": "up",
      "accidental": "#",
      "lyric": null
    }}
  ]
}}
Ensure the sum of duration_quarters matches {expected_ql}.
"""

    @classmethod
    def repair_anomalous_measure(
        cls,
        m: MeasureData,
        staff_id: str,
        track: TrackData,
        image_path: Optional[str] = None,
        key_fifths: int = 0,
        staff_role: str = "vocal",
        gemini_api_key: Optional[str] = None
    ) -> List[NoteElement]:
        """
        Attempts targeted surgical repair of an anomalous measure.
        Validates the output through MusicTheoryEngine before applying.
        """
        expected_ql = m.quarter_length
        current_sum = sum(el.duration_quarters for el in track.elements)

        # If already balanced and in range, no surgical repair needed
        if abs(current_sum - expected_ql) < 0.05:
            return track.elements

        logger.info(
            f"Surgical repair triggered for M{m.measure_number} staff {staff_id} "
            f"(current={current_sum:.2f}ql, expected={expected_ql:.2f}ql)"
        )

        # 1. If an image path is available, try vision LLM surgical patch
        if image_path and Path(image_path).exists():
            patch = cls._query_vision_repair(
                image_path=image_path,
                m=m,
                clef=track.clef,
                key_fifths=key_fifths,
                staff_role=staff_role,
                gemini_api_key=gemini_api_key
            )
            if patch:
                # Validate and quantize rhythm through MusicTheoryEngine
                solved = MusicTheoryEngine.solve_measure_rhythm(
                    patch,
                    bar_quarter_length=expected_ql,
                    time_signature=m.time_signature
                )
                logger.info(f"Surgical patch successfully applied to M{m.measure_number} {staff_id}")
                return solved

        # 2. Deterministic Music Theory repair fallback: quantize and re-balance beat grid
        logger.info(f"Applying deterministic MusicTheory beat-grid quantization to M{m.measure_number} {staff_id}")
        return MusicTheoryEngine.solve_measure_rhythm(
            track.elements,
            bar_quarter_length=expected_ql,
            time_signature=m.time_signature
        )

    @classmethod
    def _query_vision_repair(
        cls,
        image_path: str,
        m: MeasureData,
        clef: str,
        key_fifths: int,
        staff_role: str,
        gemini_api_key: Optional[str] = None
    ) -> Optional[List[NoteElement]]:
        """Invokes Gemini Vision or local Ollama for the single measure crop."""
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")

            prompt = cls.SURGICAL_PROMPT_TEMPLATE.format(
                clef=clef,
                time_signature=m.time_signature,
                expected_ql=m.quarter_length,
                key_fifths=key_fifths,
                staff_role=staff_role
            )

            # Try local Ollama if configured
            ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
            try:
                resp = requests.post(
                    f"{ollama_url}/api/generate",
                    json={
                        "model": "llama3.2-vision:latest",
                        "prompt": prompt,
                        "images": [img_b64],
                        "stream": False,
                        "format": "json"
                    },
                    timeout=10
                )
                if resp.status_code == 200:
                    raw_text = resp.json().get("response", "")
                    parsed = json.loads(raw_text)
                    return cls._parse_llm_notes(parsed.get("notes", []))
            except Exception:
                pass

            # Try Gemini API if key is present
            api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY")
            if api_key:
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
                payload = {
                    "contents": [{
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": "image/png", "data": img_b64}}
                        ]
                    }],
                    "generationConfig": {"response_mime_type": "application/json"}
                }
                resp = requests.post(gemini_url, json=payload, timeout=12)
                if resp.status_code == 200:
                    candidates = resp.json().get("candidates", [])
                    if candidates:
                        raw_json = candidates[0]["content"]["parts"][0]["text"]
                        parsed = json.loads(raw_json)
                        return cls._parse_llm_notes(parsed.get("notes", []))

        except Exception as ex:
            logger.warning(f"Vision surgical repair encountered error: {ex}")

        return None

    @classmethod
    def _parse_llm_notes(cls, raw_notes: List[Dict[str, Any]]) -> List[NoteElement]:
        results: List[NoteElement] = []
        cur_offset = 0.0
        for n in raw_notes:
            dur = float(n.get("duration_quarters", 1.0))
            is_r = bool(n.get("is_rest", False))
            p = None if is_r else n.get("pitch")
            stem = n.get("stem_direction")
            acc = n.get("accidental")
            lyr = n.get("lyric")
            m_pitch = MusicTheoryEngine.pitch_to_midi(p) if p else None

            results.append(
                NoteElement(
                    pitch=p,
                    midi_pitch=m_pitch,
                    duration_quarters=dur,
                    offset_quarters=cur_offset,
                    is_rest=is_r,
                    stem_direction=stem,
                    accidental=acc,
                    lyric=lyr
                )
            )
            cur_offset += dur
        return results
