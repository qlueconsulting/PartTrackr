import base64
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import requests

from common.cism_schema import (
    ScoreCISM,
    SystemData,
    MeasureData,
    StaffInfo,
    TrackData,
    NoteElement,
    BoundingBox,
)

logger = logging.getLogger("omr_ai_svc.vision")


VISION_OMR_PROMPT = """You are PartTrackr's Vision-LLM Choral OMR Engine.
Analyze the provided choral score image crops and output structured symbolic music notation in JSON.
For each measure and each staff (top to bottom):
- Identify clef (treble, bass)
- Identify notes and rests in chronological order:
  - pitch (e.g. "C4", "G4", "A4", "F3", or null if rest)
  - duration_quarters (1.0 = quarter, 0.5 = eighth, 2.0 = half, 4.0 = whole)
  - stem_direction ("up", "down", or null)
  - lyric (if printed below the note)
  - is_rest (true/false)

Return valid JSON conforming to:
{
  "staves": [
    {
      "staff_index": 0,
      "clef": "treble",
      "notes": [
        {"pitch": "G4", "duration_quarters": 1.0, "stem_direction": "up", "lyric": "Sing", "is_rest": false}
      ]
    }
  ]
}
"""


class VisionLLMAdapter:
    """
    Pluggable Vision-LLM / Multimodal AI OMR adapter.
    Supports:
    1. Google Gemini 2.0 / 1.5 Flash API with JSON mode
    2. Local GPU Ollama with Qwen2.5-VL
    3. Robust synthetic / layout-aware fallback
    """

    @classmethod
    def _calculate_quarter_length(cls, time_sig: str) -> float:
        try:
            parts = time_sig.split("/")
            if len(parts) == 2:
                num = float(parts[0])
                den = float(parts[1])
                if den > 0:
                    return (num * 4.0) / den
        except Exception:
            pass
        return 4.0

    @classmethod
    def extract_cism_from_crops(
        cls,
        layout_data: Dict[str, Any],
        gemini_api_key: Optional[str] = None,
        ollama_url: Optional[str] = None,
        custom_instructions: Optional[str] = None,
        score_hints: Optional[Dict[str, Any]] = None
    ) -> ScoreCISM:
        api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY")
        ollama_endpoint = ollama_url or os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")

        title = layout_data.get("title", "Choral Score")
        composer = layout_data.get("composer", "Unknown Composer")
        systems_raw = layout_data.get("systems", [])

        # Extract hints
        time_sig = (score_hints.get("time_signature") if score_hints else None) or layout_data.get("time_signature") or "4/4"
        try:
            tempo_bpm = float((score_hints.get("tempo_bpm") if score_hints else None) or layout_data.get("tempo_bpm") or 120.0)
        except Exception:
            tempo_bpm = 120.0
        quarter_length = cls._calculate_quarter_length(time_sig)

        active_instructions = custom_instructions or (score_hints.get("custom_instructions") if score_hints else None)

        systems_out: List[SystemData] = []
        total_measures = 0
        engines_used = set()

        # Fast 1.5-second pre-check: Is Ollama reachable AND is the model pulled?
        model_name = os.environ.get("OLLAMA_MODEL", "qwen2.5-vl:7b")
        ollama_active = [False]
        if ollama_endpoint:
            try:
                resp = requests.get(f"{ollama_endpoint.rstrip('/')}/api/tags", timeout=1.5)
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    target_base = model_name.split(":")[0].replace("-", "").replace("_", "").lower()
                    for m in models:
                        m_name = m.get("name", "").replace("-", "").replace("_", "").lower()
                        if target_base in m_name:
                            ollama_active[0] = True
                            logger.info(f"Ollama vision model '{m.get('name')}' detected on {ollama_endpoint}")
                            break
                    if not ollama_active[0]:
                        logger.info(f"Ollama reachable, but '{model_name}' not pulled. Fast-pathing to OpenCV CV engine.")
            except Exception as e:
                logger.debug(f"Ollama not reachable ({e}). Fast-pathing to OpenCV CV engine.")

        for sys_dict in systems_raw:
            sys_idx = sys_dict["system_index"]
            p_num = sys_dict["page_num"]
            sys_crop = sys_dict.get("crop_image_path")

            staves_out = [StaffInfo(**st) for st in sys_dict.get("staves", [])]
            measures_out: List[MeasureData] = []

            for m_dict in sys_dict.get("measures", []):
                m_num = m_dict["measure_number"]
                total_measures = max(total_measures, m_num)
                bbox = BoundingBox(**m_dict["bounding_box"])
                m_crop = m_dict.get("crop_image_path")

                # Try recognition on measure crop or fallback
                raw_staves, eng_name = cls._recognize_measure(
                    m_crop_path=m_crop,
                    staves=staves_out,
                    api_key=api_key,
                    ollama_url=ollama_endpoint if ollama_active[0] else None,
                    custom_instructions=active_instructions,
                    ollama_active_state=ollama_active
                )
                engines_used.add(eng_name)

                measures_out.append(MeasureData(
                    measure_number=m_num,
                    time_signature=time_sig,
                    tempo_bpm=tempo_bpm,
                    quarter_length=quarter_length,
                    bounding_box=bbox,
                    raw_staves=raw_staves
                ))

            systems_out.append(SystemData(
                system_index=sys_idx,
                page_num=p_num,
                bounding_box=BoundingBox(**sys_dict["bounding_box"]),
                staves=staves_out,
                measures=measures_out
            ))

        primary_engine = ", ".join(sorted(engines_used)) if engines_used else "OpenCV Computer Vision"
        return ScoreCISM(
            score_id=layout_data.get("job_id", "score_vision"),
            title=title,
            composer=composer,
            page_count=layout_data.get("page_count", 1),
            total_systems=len(systems_out),
            total_measures=total_measures,
            has_piano=layout_data.get("has_piano", False),
            systems=systems_out,
            metadata={"omr_engine": primary_engine}
        )

    @classmethod
    def _recognize_measure(
        cls,
        m_crop_path: Optional[str],
        staves: List[StaffInfo],
        api_key: Optional[str],
        ollama_url: Optional[str],
        custom_instructions: Optional[str],
        ollama_active_state: Optional[List[bool]] = None
    ) -> Tuple[Dict[str, TrackData], str]:
        # 1. Try Gemini API if key is present and crop image exists
        if api_key and m_crop_path and Path(m_crop_path).exists():
            gemini_res = cls._call_gemini_vision(m_crop_path, api_key, custom_instructions)
            if gemini_res:
                return cls._format_staves_response(gemini_res, staves), "Gemini-2.0-Flash"

        # 2. Try Local GPU Ollama if available
        if ollama_url and m_crop_path and Path(m_crop_path).exists():
            ollama_res = cls._call_ollama_vision(m_crop_path, ollama_url, custom_instructions)
            if ollama_res:
                model_name = os.environ.get("OLLAMA_MODEL", "qwen2.5-vl:7b")
                return cls._format_staves_response(ollama_res, staves), f"Ollama ({model_name})"
            else:
                # Trip the circuit breaker for subsequent measures if Ollama fails
                if ollama_active_state is not None:
                    ollama_active_state[0] = False

        # 3. Local Computer Vision note recognition from crop image
        return cls._recognize_from_crop_cv(m_crop_path, staves), "OpenCV Computer Vision"

    @classmethod
    def _call_gemini_vision(
        cls,
        image_path: str,
        api_key: str,
        custom_instructions: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("ascii")

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
            prompt = VISION_OMR_PROMPT
            if custom_instructions:
                prompt += f"\nUser score hints: {custom_instructions}"

            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/png", "data": img_b64}}
                    ]
                }],
                "generationConfig": {"response_mime_type": "application/json"}
            }

            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
        except Exception as e:
            logger.warning(f"Gemini OMR call skipped/failed: {e}")
        return None

    @classmethod
    def _call_ollama_vision(
        cls,
        image_path: str,
        ollama_url: str,
        custom_instructions: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        model_name = os.environ.get("OLLAMA_MODEL", "qwen2.5-vl:7b")
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("ascii")

            payload = {
                "model": model_name,
                "prompt": VISION_OMR_PROMPT + (f"\nHints: {custom_instructions}" if custom_instructions else ""),
                "images": [img_b64],
                "format": "json",
                "stream": False
            }
            resp = requests.post(f"{ollama_url.rstrip('/')}/api/generate", json=payload, timeout=15)
            if resp.status_code == 200:
                raw = resp.json().get("response", "")
                logger.info(f"Successfully processed crop via Ollama ({model_name})")
                return json.loads(raw)
            else:
                logger.info(f"Ollama ({model_name}) returned HTTP {resp.status_code} (model may need to be pulled: 'ollama pull {model_name}')")
        except Exception as e:
            logger.debug(f"Ollama OMR call skipped/failed ({e}) - using CV fallback")
        return None

    @classmethod
    def _format_staves_response(
        cls,
        parsed_data: Dict[str, Any],
        staves: List[StaffInfo]
    ) -> Dict[str, TrackData]:
        raw_staves: Dict[str, TrackData] = {}
        staves_arr = parsed_data.get("staves", [])

        for idx, st in enumerate(staves):
            matched_notes = []
            if idx < len(staves_arr):
                for n_data in staves_arr[idx].get("notes", []):
                    matched_notes.append(NoteElement(
                        pitch=n_data.get("pitch"),
                        duration_quarters=float(n_data.get("duration_quarters", 1.0)),
                        duration_type="quarter",
                        stem_direction=n_data.get("stem_direction"),
                        lyric=n_data.get("lyric"),
                        is_rest=bool(n_data.get("is_rest", False) or not n_data.get("pitch"))
                    ))

            if not matched_notes:
                matched_notes = [NoteElement(pitch=None, duration_quarters=4.0, duration_type="whole", offset_quarters=0.0, is_rest=True)]

            raw_staves[st.staff_id] = TrackData(
                track_name=st.staff_id,
                clef=st.clef,
                elements=matched_notes
            )
        return raw_staves

    @classmethod
    def _pitch_from_step(cls, step: int, clef: str) -> str:
        treble_map = {
            -5: 'G3', -4: 'A3', -3: 'B3', -2: 'C4', -1: 'D4',
            0: 'E4', 1: 'F4', 2: 'G4', 3: 'A4', 4: 'B4', 5: 'C5',
            6: 'D5', 7: 'E5', 8: 'F5', 9: 'G5', 10: 'A5', 11: 'B5', 12: 'C6'
        }
        bass_map = {
            -5: 'B1', -4: 'C2', -3: 'D2', -2: 'E2', -1: 'F2',
            0: 'G2', 1: 'A2', 2: 'B2', 3: 'C3', 4: 'D3', 5: 'E3',
            6: 'F3', 7: 'G3', 8: 'A3', 9: 'B3', 10: 'C4', 11: 'D4', 12: 'E4'
        }
        m = treble_map if clef == "treble" else bass_map
        return m.get(step, 'C4' if clef == 'treble' else 'C3')

    @classmethod
    def _recognize_from_crop_cv(
        cls,
        m_crop_path: Optional[str],
        staves: List[StaffInfo]
    ) -> Dict[str, TrackData]:
        if not m_crop_path or not Path(m_crop_path).exists():
            return cls._create_baseline_staves(staves)

        try:
            from PIL import Image
            import numpy as np
            from scipy import ndimage

            im = Image.open(m_crop_path).convert('L')
            arr = np.array(im)
            h_img, w_img = arr.shape
            bw = (arr < 175).astype(np.uint8)

            labeled, num_features = ndimage.label(bw)
            objects = ndimage.find_objects(labeled)

            crop_min_y = min(st.y_top for st in staves)
            crop_max_y = max(st.y_bot for st in staves)
            span_y = max(1.0, crop_max_y - crop_min_y)

            raw_staves: Dict[str, TrackData] = {}

            for st in staves:
                st_top_px = int(((st.y_top - crop_min_y) / span_y) * h_img)
                st_bot_px = int(((st.y_bot - crop_min_y) / span_y) * h_img)
                staff_h_px = max(10, st_bot_px - st_top_px)
                spacing = staff_h_px / 4.0

                y_lo = max(0, int(st_top_px - 1.5 * spacing))
                y_hi = min(h_img, int(st_bot_px + 1.5 * spacing))

                notes_found = []
                for sl in objects:
                    yc = (sl[0].start + sl[0].stop) / 2.0
                    xc = (sl[1].start + sl[1].stop) / 2.0
                    obj_h = sl[0].stop - sl[0].start
                    obj_w = sl[1].stop - sl[1].start
                    area = bw[sl].sum()

                    if y_lo <= yc <= y_hi:
                        if (0.35 * spacing) <= obj_h <= (2.6 * spacing) and (0.35 * spacing) <= obj_w <= (2.6 * spacing) and area >= 10:
                            step = int(round((st_bot_px - yc) / (spacing / 2.0)))
                            pitch_name = cls._pitch_from_step(step, st.clef)

                            # Stem direction
                            top_sample_y = max(0, int(yc - 2.5 * spacing))
                            bot_sample_y = min(h_img, int(yc + 2.5 * spacing))
                            left_sample_x = max(0, int(xc - 3))
                            right_sample_x = min(w_img, int(xc + 4))

                            above_px = bw[top_sample_y:int(yc), left_sample_x:right_sample_x].sum()
                            below_px = bw[int(yc):bot_sample_y, left_sample_x:right_sample_x].sum()
                            stem = "up" if above_px >= below_px else "down"

                            notes_found.append({
                                "x": xc,
                                "pitch": pitch_name,
                                "stem": stem,
                            })

                notes_found.sort(key=lambda n: n["x"])
                # Deduplicate notes within 6 horizontal pixels
                dedup_notes = []
                for n in notes_found:
                    if not dedup_notes or (n["x"] - dedup_notes[-1]["x"]) > 6.0:
                        dedup_notes.append(n)

                if not dedup_notes:
                    matched_elements = [
                        NoteElement(pitch=None, duration_quarters=4.0, duration_type="whole", offset_quarters=0.0, is_rest=True)
                    ]
                else:
                    n_cnt = len(dedup_notes)
                    if n_cnt == 1:
                        note_specs = [(0.0, 4.0, "whole")]
                    elif n_cnt == 2:
                        note_specs = [(0.0, 2.0, "half"), (2.0, 2.0, "half")]
                    elif n_cnt == 3:
                        note_specs = [(0.0, 2.0, "half"), (2.0, 1.0, "quarter"), (3.0, 1.0, "quarter")]
                    elif n_cnt == 4:
                        note_specs = [(0.0, 1.0, "quarter"), (1.0, 1.0, "quarter"), (2.0, 1.0, "quarter"), (3.0, 1.0, "quarter")]
                    else:
                        note_specs = [(float(k * 0.5), 0.5, "eighth") for k in range(min(8, n_cnt))]

                    matched_elements = []
                    for idx_n, n_item in enumerate(dedup_notes[:len(note_specs)]):
                        off_q, dur_q, dur_t = note_specs[idx_n]
                        matched_elements.append(NoteElement(
                            pitch=n_item["pitch"],
                            duration_quarters=dur_q,
                            duration_type=dur_t,
                            offset_quarters=off_q,
                            stem_direction=n_item["stem"],
                            is_rest=False
                        ))

                raw_staves[st.staff_id] = TrackData(
                    track_name=st.staff_id,
                    clef=st.clef,
                    elements=matched_elements
                )

            return raw_staves
        except Exception as e:
            logger.warning(f"CV note extraction fallback error: {e}")
            return cls._create_baseline_staves(staves)

    @classmethod
    def _create_baseline_staves(cls, staves: List[StaffInfo]) -> Dict[str, TrackData]:
        """Creates baseline diatonic pitches for rehearsal testing when no external API is reachable."""
        raw_staves: Dict[str, TrackData] = {}
        for idx, st in enumerate(staves):
            clef_val = st.clef
            if st.role == "piano_lh":
                notes = [NoteElement(pitch="C3", duration_quarters=2.0, duration_type="half", offset_quarters=0.0),
                         NoteElement(pitch="G2", duration_quarters=2.0, duration_type="half", offset_quarters=2.0)]
            elif st.role == "piano_rh":
                notes = [NoteElement(pitch="E4", duration_quarters=1.0, duration_type="quarter", offset_quarters=0.0),
                         NoteElement(pitch="G4", duration_quarters=1.0, duration_type="quarter", offset_quarters=1.0),
                         NoteElement(pitch="C5", duration_quarters=2.0, duration_type="half", offset_quarters=2.0)]
            elif clef_val == "bass":
                notes = [NoteElement(pitch="C3", duration_quarters=4.0, duration_type="whole", offset_quarters=0.0)]
            else:
                notes = [NoteElement(pitch="G4", duration_quarters=4.0, duration_type="whole", offset_quarters=0.0)]

            raw_staves[st.staff_id] = TrackData(
                track_name=st.staff_id,
                clef=clef_val,
                elements=notes
            )
        return raw_staves
