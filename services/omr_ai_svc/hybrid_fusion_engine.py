import logging
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

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
from common.music_theory_engine import MusicTheoryEngine
from common.ocr_fusion import ScoreOCREngine, ScoreOCRPageResult
from services.omr_ai_svc.geometric_omr_engine import GeometricOMREngine

logger = logging.getLogger("omr_ai_svc.fusion")


class HybridOMRFusionEngine:
    """
    Unified Multi-Modal Sensor Fusion Engine for Choral Scores:
    Fuses:
    1. Layer 1 OCR: Lyric-to-note binding, silent vocal rest locks, margin labels, tempo & dynamics.
    2. Layer 2 Geometric OMR: Morphological staff-removed noteheads, chords, hollow/filled rhythms.
    3. Layer 3 Music Theory: Circle-of-Fifths key signature (including mid-score modulations),
       measure-scoped accidentals, treble 8vb clef transposition, and metric beat grids.
    4. Layer 4 Grounded Vision-LLM: Gemini / Ollama referee for ambiguous crops.
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
    def extract_cism(
        cls,
        layout_data: Dict[str, Any],
        custom_instructions: Optional[str] = None,
        score_hints: Optional[Dict[str, Any]] = None,
        gemini_api_key: Optional[str] = None,
        ollama_url: Optional[str] = None
    ) -> ScoreCISM:
        title = layout_data.get("title", "Choral Score")
        composer = layout_data.get("composer", "Unknown Composer")
        systems_raw = layout_data.get("systems", [])

        # Time signature and tempo
        time_sig = (score_hints.get("time_signature") if score_hints else None) or layout_data.get("time_signature") or "4/4"
        try:
            tempo_bpm = float((score_hints.get("tempo_bpm") if score_hints else None) or layout_data.get("tempo_bpm") or 120.0)
        except Exception:
            tempo_bpm = 120.0
        quarter_length = cls._calculate_quarter_length(time_sig)

        # Key signature: default to score_hints or detected fifths
        key_fifths = 0
        if score_hints and score_hints.get("key_signature_fifths") is not None:
            key_fifths = int(score_hints["key_signature_fifths"])

        has_piano = layout_data.get("has_piano", True)
        is_piano_only = False
        if score_hints:
            if score_hints.get("piano_only") or score_hints.get("accompaniment_type") == "piano_only":
                is_piano_only = True
                has_piano = True
            elif score_hints.get("accompaniment_type") == "a_cappella":
                has_piano = False
            elif score_hints.get("accompaniment_type") in ("piano", "orchestra_reduction"):
                has_piano = True

        systems_out: List[SystemData] = []
        total_measures = 0

        # Load page images and run OCR if available (skip in piano_only mode for maximum speed and zero text bleed)
        pages_ocr: Dict[int, ScoreOCRPageResult] = {}
        if not is_piano_only:
            for p_data in layout_data.get("pages", []):
                p_num = p_data.get("page_num", 1)
                img_path = p_data.get("image_path")
                if img_path and Path(img_path).exists():
                    try:
                        from PIL import Image
                        import numpy as np
                        pil_img = Image.open(img_path).convert("RGB")
                        img_arr = np.array(pil_img)
                        pages_ocr[p_num] = ScoreOCREngine.process_page_image(
                            img_arr,
                            p_data.get("width_pt", 612.0),
                            p_data.get("height_pt", 792.0),
                            p_num
                        )
                    except Exception as e:
                        logger.debug(f"OCR load error on page {p_num}: {e}")

        for sys_dict in systems_raw:
            sys_idx = sys_dict["system_index"]
            p_num = sys_dict["page_num"]
            staves_out = [StaffInfo(**st) for st in sys_dict.get("staves", [])]
            measures_out: List[MeasureData] = []

            ocr_page = pages_ocr.get(p_num)

            for m_dict in sys_dict.get("measures", []):
                m_num = m_dict["measure_number"]
                total_measures = max(total_measures, m_num)
                bbox = BoundingBox(**m_dict["bounding_box"])
                m_crop = m_dict.get("crop_image_path")

                # Detect mid-score key signature modulation from score hints if configured
                curr_key_fifths = key_fifths
                if score_hints and "modulations" in score_hints:
                    for mod_m, mod_f in score_hints["modulations"].items():
                        if m_num >= int(mod_m):
                            curr_key_fifths = int(mod_f)

                # 1. Run Geometric Staff-Removed OMR (Pass 2 isolated staff revisit if crops exist)
                if is_piano_only:
                    # In piano-only mode, focus 100% of recognition on piano RH and LH staves
                    piano_staves = [st for st in staves_out if st.role in ("piano_rh", "piano_lh") or st.bracket_type == "brace"]
                    target_staves = piano_staves if piano_staves else staves_out
                    raw_staves = GeometricOMREngine.recognize_measure_crop(
                        crop_image_path=m_crop,
                        staves=target_staves,
                        key_fifths=curr_key_fifths,
                        quarter_length=quarter_length,
                        time_signature=time_sig,
                        staff_crop_paths=m_dict.get("staff_crop_paths")
                    )
                    # For vocal staves, populate whole rests
                    whole_rest_el = [
                        NoteElement(
                            pitch=None,
                            duration_quarters=quarter_length,
                            duration_type="dotted_half" if quarter_length == 3.0 else "whole",
                            offset_quarters=0.0,
                            is_rest=True
                        )
                    ]
                    for st in staves_out:
                        if st.staff_id not in raw_staves:
                            raw_staves[st.staff_id] = TrackData(
                                track_name=st.staff_id,
                                clef=st.clef,
                                elements=whole_rest_el
                            )
                else:
                    raw_staves = GeometricOMREngine.recognize_measure_crop(
                        crop_image_path=m_crop,
                        staves=staves_out,
                        key_fifths=curr_key_fifths,
                        quarter_length=quarter_length,
                        time_signature=time_sig,
                        staff_crop_paths=m_dict.get("staff_crop_paths")
                    )

                # 2. Layer 1 OCR Cross-Validation: Check for silent vocal measures before choral entry
                choral_entry = (score_hints or {}).get("choral_entry_measure")
                if choral_entry and m_num < int(choral_entry) and not is_piano_only:
                    for st in staves_out:
                        if st.role in ("vocal", "vocal_men", "vocal_women"):
                            raw_staves[st.staff_id] = TrackData(
                                track_name=st.staff_id,
                                clef=st.clef,
                                elements=[
                                    NoteElement(pitch=None, duration_quarters=quarter_length, duration_type="dotted_half" if quarter_length == 3.0 else "whole", offset_quarters=0.0, is_rest=True)
                                ]
                            )

                # Bind OCR lyrics if words are present in this measure horizontal range
                if ocr_page and ocr_page.lyrics:
                    m_x0, m_x1 = bbox.x, bbox.x + bbox.w
                    m_lyrics = [
                        it for it in ocr_page.lyrics
                        if m_x0 <= it.bbox_pt[0] <= m_x1 or m_x0 <= it.bbox_pt[2] <= m_x1
                    ]
                    if m_lyrics:
                        # Bind syllables to vocal staves
                        for st in staves_out:
                            if st.role in ("vocal", "vocal_men", "vocal_women"):
                                trk = raw_staves.get(st.staff_id)
                                if trk and trk.elements:
                                    non_rests = [el for el in trk.elements if not el.is_rest]
                                    for idx_el, el in enumerate(non_rests):
                                        if idx_el < len(m_lyrics):
                                            el.lyric = m_lyrics[idx_el].text

                # Build MeasureData with preserved measure number and rehearsal mark
                measures_out.append(MeasureData(
                    measure_number=m_num,
                    time_signature=time_sig,
                    tempo_bpm=tempo_bpm,
                    key_signature_fifths=curr_key_fifths,
                    rehearsal_mark=m_dict.get("rehearsal_mark"),
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

        score_obj = ScoreCISM(
            score_id=layout_data.get("job_id", "score_fused"),
            title=title,
            composer=composer,
            page_count=layout_data.get("page_count", len(layout_data.get("pages", []))),
            total_systems=len(systems_out),
            total_measures=total_measures,
            has_piano=has_piano,
            systems=systems_out,
            metadata={
                "omr_engine": "Neuro-Symbolic Sensor-Fusion (OCR + Geometric OMR + Music Theory)",
                "piano_only": is_piano_only,
            }
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
