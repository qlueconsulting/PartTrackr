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
from common.lockstep_utils import reconcile_cism_measures
from common.learning_store import LearningManager, ScoreStyleFingerprint

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
    def build_ground_truth_prompt(
        cls,
        custom_instructions: Optional[str] = None,
        score_hints: Optional[Dict[str, Any]] = None,
        composer: str = "",
        layout_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        prompt = VISION_OMR_PROMPT
        facts = []
        if score_hints:
            if score_hints.get("total_measures"):
                facts.append(f"- Verified Total Measures in Piece: {score_hints['total_measures']}")
            if score_hints.get("time_signature"):
                facts.append(f"- Verified Time Signature: {score_hints['time_signature']}")
            if score_hints.get("tempo_bpm"):
                facts.append(f"- Verified Starting Tempo: {score_hints['tempo_bpm']} BPM")
            if score_hints.get("choral_voicing"):
                facts.append(f"- Verified Choral Voicing: {score_hints['choral_voicing']}")
            if score_hints.get("accompaniment_type"):
                facts.append(f"- Verified Accompaniment: {score_hints['accompaniment_type']}")
            if score_hints.get("has_piano") is not None:
                facts.append(f"- Score Has Piano: {score_hints['has_piano']}")
            if score_hints.get("staves_per_system"):
                facts.append(f"- Staves Per System: {score_hints['staves_per_system']}")
            if score_hints.get("part_layout_summary"):
                facts.append(f"- Part Layout: {score_hints['part_layout_summary']}")

        active_instr = custom_instructions or (score_hints.get("custom_instructions") if score_hints else None)
        if active_instr:
            facts.append(f"- User Score Directives: {active_instr}")

        # Inject learned exemplar blueprints from self-learning memory
        staves_cnt = 3
        if score_hints and score_hints.get("staves_per_system"):
            staves_cnt = int(score_hints["staves_per_system"])
        elif layout_data and layout_data.get("staves_per_system"):
            staves_cnt = int(layout_data["staves_per_system"])

        time_sig = (score_hints.get("time_signature") if score_hints else None) or (layout_data.get("time_signature") if layout_data else None) or "4/4"
        fingerprint = ScoreStyleFingerprint(
            staves_per_system=staves_cnt,
            time_signature=time_sig,
            has_brace=bool(score_hints.get("accompaniment_type") in ("piano", "orchestra_reduction") if score_hints else True)
        )
        few_shot_context = LearningManager.get_few_shot_prompt_text(fingerprint, composer=composer)
        if few_shot_context:
            prompt += f"\n\n{few_shot_context}"

        if facts:
            prompt += "\n\nCRITICAL USER-VERIFIED GROUND TRUTH FACTS:\n" + "\n".join(facts)
            prompt += "\nYou MUST strictly conform to these ground-truth facts when identifying notes, rests, barlines, and staves."

        prompt += "\n\nSTRICT NEGATIVE CONSTRAINTS (ZERO TOLERANCE FOR HALLUCINATION):\n"
        prompt += "- DO NOT invent, guess, extrapolate, or hallucinate notes or rests.\n"
        prompt += "- If a staff or measure contains no discernible notes or is empty, output a rest with is_rest: true, pitch: null.\n"
        prompt += "- NEVER inject placeholder diatonic notes (such as C3, G2, E4, G4, C5). If you cannot read a notehead, emit a rest.\n"
        return prompt

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

        # Fast pre-check: Probe Ollama candidate endpoints and resolve the exact model name
        candidates = [
            ollama_url,
            os.environ.get("OLLAMA_BASE_URL"),
            "http://192.168.2.4:11434",
            "http://localhost:11434",
            "http://127.0.0.1:11434",
            "http://ollama:11434",
            "http://host.docker.internal:11434"
        ]
        active_endpoint = None
        resolved_model_name = [os.environ.get("OLLAMA_MODEL", "qwen2.5vl:7b")]
        ollama_active = [False]

        for cand in candidates:
            if not cand:
                continue
            cand_clean = cand.rstrip("/")
            try:
                resp = requests.get(f"{cand_clean}/api/tags", timeout=1.0)
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    target_base = resolved_model_name[0].split(":")[0].replace("-", "").replace("_", "").lower()
                    for m in models:
                        m_name = m.get("name", "")
                        clean_m = m_name.replace("-", "").replace("_", "").lower()
                        if target_base in clean_m or "qwen" in clean_m or "vision" in clean_m:
                            ollama_active[0] = True
                            active_endpoint = cand_clean
                            resolved_model_name[0] = m_name
                            logger.info(f"Ollama vision model '{m_name}' detected on {cand_clean}")
                            break
                    if ollama_active[0]:
                        break
            except Exception:
                continue

        if not ollama_active[0]:
            logger.info(f"Ollama endpoint not active or model not pulled. Fast-pathing to OpenCV CV engine.")


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
                    ollama_url=active_endpoint if ollama_active[0] else None,
                    ollama_model=resolved_model_name[0] if ollama_active[0] else None,
                    custom_instructions=active_instructions,
                    score_hints=score_hints,
                    ollama_active_state=ollama_active,
                    quarter_length=quarter_length,
                    composer=composer,
                    layout_data=layout_data
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
        
        has_piano = layout_data.get("has_piano", False)
        if score_hints:
            if score_hints.get("accompaniment_type") == "a_cappella":
                has_piano = False
            elif score_hints.get("accompaniment_type") in ("piano", "orchestra_reduction"):
                has_piano = True

        score_obj = ScoreCISM(
            score_id=layout_data.get("job_id", "score_vision"),
            title=title,
            composer=composer,
            page_count=layout_data.get("page_count", 1),
            total_systems=len(systems_out),
            total_measures=total_measures,
            has_piano=has_piano,
            systems=systems_out,
            metadata={"omr_engine": primary_engine}
        )

        target_measures = score_hints.get("total_measures") if score_hints else None
        if target_measures:
            score_obj = reconcile_cism_measures(
                score_obj,
                target_total_measures=int(target_measures),
                target_time_signature=time_sig,
                target_tempo_bpm=tempo_bpm,
                has_piano=has_piano
            )

        return score_obj

    @classmethod
    def _recognize_measure(
        cls,
        m_crop_path: Optional[str],
        staves: List[StaffInfo],
        api_key: Optional[str],
        ollama_url: Optional[str],
        ollama_model: Optional[str] = None,
        custom_instructions: Optional[str] = None,
        score_hints: Optional[Dict[str, Any]] = None,
        ollama_active_state: Optional[List[bool]] = None,
        quarter_length: float = 4.0,
        composer: str = "",
        layout_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, TrackData], str]:
        # 1. Try Gemini API if key is present and crop image exists
        if api_key and m_crop_path and Path(m_crop_path).exists():
            gemini_res = cls._call_gemini_vision(m_crop_path, api_key, custom_instructions, score_hints, composer=composer, layout_data=layout_data)
            if gemini_res:
                return cls._format_staves_response(gemini_res, staves, quarter_length=quarter_length), "Gemini-2.0-Flash"

        # 2. Try Local GPU Ollama if available
        if ollama_url and m_crop_path and Path(m_crop_path).exists():
            ollama_res = cls._call_ollama_vision(
                m_crop_path, ollama_url,
                model_name=ollama_model or os.environ.get("OLLAMA_MODEL", "qwen2.5vl:7b"),
                custom_instructions=custom_instructions, score_hints=score_hints,
                composer=composer, layout_data=layout_data
            )
            if ollama_res:
                used_model = ollama_model or os.environ.get("OLLAMA_MODEL", "qwen2.5vl:7b")
                return cls._format_staves_response(ollama_res, staves, quarter_length=quarter_length), f"Ollama ({used_model})"
            else:
                # Trip the circuit breaker for subsequent measures if Ollama fails
                if ollama_active_state is not None:
                    ollama_active_state[0] = False

        # 3. Local Computer Vision note recognition from crop image
        return cls._recognize_from_crop_cv(m_crop_path, staves, quarter_length=quarter_length), "OpenCV Computer Vision"

    @classmethod
    def _call_gemini_vision(
        cls,
        image_path: str,
        api_key: str,
        custom_instructions: Optional[str] = None,
        score_hints: Optional[Dict[str, Any]] = None,
        composer: str = "",
        layout_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("ascii")

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
            prompt = cls.build_ground_truth_prompt(custom_instructions, score_hints, composer=composer, layout_data=layout_data)

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
        model_name: Optional[str] = None,
        custom_instructions: Optional[str] = None,
        score_hints: Optional[Dict[str, Any]] = None,
        composer: str = "",
        layout_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        target_model = model_name or os.environ.get("OLLAMA_MODEL", "qwen2.5vl:7b")
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("ascii")

            prompt = cls.build_ground_truth_prompt(custom_instructions, score_hints, composer=composer, layout_data=layout_data)
            payload = {
                "model": target_model,
                "prompt": prompt,
                "images": [img_b64],
                "format": "json",
                "stream": False
            }
            resp = requests.post(f"{ollama_url.rstrip('/')}/api/generate", json=payload, timeout=15)
            if resp.status_code == 200:
                raw = resp.json().get("response", "")
                logger.info(f"Successfully processed crop via Ollama ({target_model})")
                return json.loads(raw)
            else:
                logger.info(f"Ollama ({target_model}) returned HTTP {resp.status_code} (model may need to be pulled: 'ollama pull {target_model}')")
        except Exception as e:
            logger.debug(f"Ollama OMR call skipped/failed ({e}) - using CV fallback")
        return None

    @classmethod
    def _format_staves_response(
        cls,
        parsed_data: Dict[str, Any],
        staves: List[StaffInfo],
        quarter_length: float = 4.0
    ) -> Dict[str, TrackData]:
        raw_staves: Dict[str, TrackData] = {}
        staves_arr = parsed_data.get("staves", [])
        dur_type = "whole" if quarter_length >= 4.0 else ("half" if quarter_length >= 2.0 else "quarter")

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
                matched_notes = [NoteElement(pitch=None, duration_quarters=quarter_length, duration_type=dur_type, offset_quarters=0.0, is_rest=True)]

            raw_staves[st.staff_id] = TrackData(
                track_name=st.staff_id,
                clef=st.clef,
                elements=matched_notes
            )
        return raw_staves

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
        staves: List[StaffInfo],
        quarter_length: float = 4.0
    ) -> Dict[str, TrackData]:
        if not m_crop_path or not Path(m_crop_path).exists():
            return cls._create_baseline_staves(staves, quarter_length=quarter_length)

        dur_type_full = "whole" if quarter_length >= 4.0 else ("half" if quarter_length >= 2.0 else "quarter")

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
                        NoteElement(pitch=None, duration_quarters=quarter_length, duration_type=dur_type_full, offset_quarters=0.0, is_rest=True)
                    ]
                else:
                    n_cnt = len(dedup_notes)
                    dur_each = float(quarter_length / n_cnt)
                    matched_elements = []
                    for idx_n, n_item in enumerate(dedup_notes):
                        off_q = float(idx_n * dur_each)
                        dur_t = "quarter" if abs(dur_each - 1.0) < 0.1 else ("half" if abs(dur_each - 2.0) < 0.1 else "eighth")
                        matched_elements.append(NoteElement(
                            pitch=n_item["pitch"],
                            duration_quarters=dur_each,
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
            return cls._create_baseline_staves(staves, quarter_length=quarter_length)

    @classmethod
    def _create_baseline_staves(cls, staves: List[StaffInfo], quarter_length: float = 4.0) -> Dict[str, TrackData]:
        """Creates clean full-measure rests for rehearsal testing when no external API or notes are detected.
        Guarantees ZERO made-up or hallucinated notes."""
        raw_staves: Dict[str, TrackData] = {}
        dur_type = "whole" if quarter_length >= 4.0 else ("half" if quarter_length >= 2.0 else "quarter")
        for idx, st in enumerate(staves):
            raw_staves[st.staff_id] = TrackData(
                track_name=st.staff_id,
                clef=st.clef,
                elements=[
                    NoteElement(
                        pitch=None,
                        duration_quarters=quarter_length,
                        duration_type=dur_type,
                        offset_quarters=0.0,
                        is_rest=True
                    )
                ]
            )
        return raw_staves
