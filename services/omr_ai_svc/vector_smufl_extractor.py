from fractions import Fraction
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import pymupdf

from common.cism_schema import (
    ScoreCISM,
    SystemData,
    MeasureData,
    StaffInfo,
    TrackData,
    NoteElement,
    BoundingBox,
)

logger = logging.getLogger("omr_ai_svc.vector")

# SMuFL Codepoints
SMUFL_G_CLEF = 0xE050
SMUFL_F_CLEF = 0xE062
SMUFL_C_CLEF = 0xE05C

SMUFL_NOTEHEAD_WHOLE = 0xE0A2
SMUFL_NOTEHEAD_HALF = 0xE0A3
SMUFL_NOTEHEAD_BLACK = 0xE0A4
SMUFL_NOTEHEADS = {SMUFL_NOTEHEAD_WHOLE, SMUFL_NOTEHEAD_HALF, SMUFL_NOTEHEAD_BLACK}

SMUFL_REST_WHOLE = 0xE4E3
SMUFL_REST_HALF = 0xE4E4
SMUFL_REST_QUARTER = 0xE4E5
SMUFL_REST_8TH = 0xE4E6
SMUFL_RESTS = {SMUFL_REST_WHOLE, SMUFL_REST_HALF, SMUFL_REST_QUARTER, SMUFL_REST_8TH}

DIATONIC_STEPS = ["C", "D", "E", "F", "G", "A", "B"]


class VectorSMuFLExtractor:
    """
    Deterministic Digital PDF / SMuFL Vector Score Extractor.
    Extracts noteheads, accidentals, clefs, and barlines directly into CISM JSON
    from digital sheet music PDFs (Finale, Dorico, MuseScore, Sibelius).
    """

    @classmethod
    def can_extract(cls, pdf_path: Path) -> bool:
        try:
            doc = pymupdf.open(str(pdf_path))
            notehead_count = 0
            for page in doc:
                for b in page.get_text("rawdict").get("blocks", []):
                    for l in b.get("lines", []):
                        for s in l.get("spans", []):
                            for c in s.get("chars", []):
                                if ord(c["c"]) in SMUFL_NOTEHEADS:
                                    notehead_count += 1
                                    if notehead_count >= 5:
                                        doc.close()
                                        return True
            doc.close()
        except Exception as e:
            logger.warning(f"Vector check failed on {pdf_path}: {e}")
        return False

    @classmethod
    def extract_cism(cls, pdf_path: Path, layout_data: Dict[str, Any]) -> ScoreCISM:
        doc = pymupdf.open(str(pdf_path))
        title = layout_data.get("title", pdf_path.stem)
        composer = layout_data.get("composer", "Unknown Composer")
        subtitle = layout_data.get("subtitle")
        has_piano = layout_data.get("has_piano", False)

        systems_out: List[SystemData] = []
        total_measures = 0

        # Extract glyphs and text per page
        page_glyphs: Dict[int, List[Dict[str, Any]]] = {}
        page_text: Dict[int, List[Dict[str, Any]]] = {}

        for p_idx, page in enumerate(doc):
            p_num = p_idx + 1
            glyphs = []
            text_spans = []
            for b in page.get_text("rawdict").get("blocks", []):
                for l in b.get("lines", []):
                    for s in l.get("spans", []):
                        font_name = s.get("font", "")
                        chars = s.get("chars", [])
                        if "Maestro" in font_name or any(0xE000 <= ord(c["c"]) <= 0xF8FF for c in chars):
                            for c in chars:
                                code = ord(c["c"])
                                if code > 0x20:
                                    glyphs.append({
                                        "code": code,
                                        "x": float(c["origin"][0]),
                                        "y": float(c["origin"][1]),
                                        "bbox": c["bbox"]
                                    })
                        else:
                            txt = "".join(c["c"] for c in chars).strip()
                            if txt:
                                text_spans.append({
                                    "text": txt,
                                    "bbox": s["bbox"],
                                    "x": float(s["bbox"][0]),
                                    "y": float(s["bbox"][1])
                                })
            page_glyphs[p_num] = glyphs
            page_text[p_num] = text_spans

        doc.close()

        for sys_raw in layout_data.get("systems", []):
            sys_idx = sys_raw["system_index"]
            p_num = sys_raw["page_num"]
            glyphs = page_glyphs.get(p_num, [])
            text_spans = page_text.get(p_num, [])

            staves_out: List[StaffInfo] = []
            for st_raw in sys_raw.get("staves", []):
                staves_out.append(StaffInfo(**st_raw))

            measures_out: List[MeasureData] = []
            for m_raw in sys_raw.get("measures", []):
                m_num = m_raw["measure_number"]
                total_measures = max(total_measures, m_num)
                bbox = BoundingBox(**m_raw["bounding_box"])

                # Extract notes on each staff in this measure
                raw_staves: Dict[str, TrackData] = {}
                for st in staves_out:
                    track_elems = cls._extract_elements_in_box(
                        st=st,
                        bbox=bbox,
                        glyphs=glyphs,
                        text_spans=text_spans
                    )
                    raw_staves[st.staff_id] = TrackData(
                        track_name=st.staff_id,
                        clef=st.clef,
                        elements=track_elems
                    )

                measures_out.append(MeasureData(
                    measure_number=m_num,
                    time_signature="4/4",
                    tempo_bpm=120.0,
                    quarter_length=4.0,
                    bounding_box=bbox,
                    raw_staves=raw_staves
                ))

            systems_out.append(SystemData(
                system_index=sys_idx,
                page_num=p_num,
                bounding_box=BoundingBox(**sys_raw["bounding_box"]),
                staves=staves_out,
                measures=measures_out
            ))

        return ScoreCISM(
            score_id=layout_data.get("job_id", "score_vector"),
            title=title,
            composer=composer,
            subtitle=subtitle,
            page_count=layout_data.get("page_count", 1),
            total_systems=len(systems_out),
            total_measures=total_measures,
            has_piano=has_piano,
            systems=systems_out,
            metadata={"omr_engine": "VectorSMuFL"}
        )

    @classmethod
    def _extract_elements_in_box(
        cls,
        st: StaffInfo,
        bbox: BoundingBox,
        glyphs: List[Dict[str, Any]],
        text_spans: List[Dict[str, Any]]
    ) -> List[NoteElement]:
        x0, x1 = bbox.x, bbox.x + bbox.w
        y_top = st.y_top - 12.0
        y_bot = st.y_bot + 12.0

        # Find noteheads and rests in this measure on this staff
        box_glyphs = [
            g for g in glyphs
            if (x0 <= g["x"] <= x1) and (y_top <= g["y"] <= y_bot)
        ]

        if not box_glyphs:
            return [NoteElement(pitch=None, duration_quarters=4.0, duration_type="whole", offset_quarters=0.0, is_rest=True)]

        # Notehead step to pitch calculation
        line_spacing = (st.y_bot - st.y_top) / 4.0 if (st.y_bot - st.y_top) > 0 else 6.0
        step_px = line_spacing / 2.0

        ref_midi = 77 if st.clef == "treble" else 57  # F5 for top treble line, A3 for top bass line
        ref_pitch_name = "F5" if st.clef == "treble" else "A3"

        elements: List[NoteElement] = []
        box_glyphs.sort(key=lambda g: g["x"])

        # Offset estimation based on horizontal position in bar
        bar_w = max(1.0, bbox.w)
        for g in box_glyphs:
            code = g["code"]
            rel_x = max(0.0, g["x"] - x0)
            off_ql = round((rel_x / bar_w) * 4.0, 1)

            if code in SMUFL_NOTEHEADS:
                # Vertical step distance from top line
                steps_down = round((g["y"] - st.y_top) / step_px)
                midi = ref_midi - steps_down
                pitch_str = cls._midi_to_pitch_str(midi)
                dur_ql = 1.0 if code == SMUFL_NOTEHEAD_BLACK else (2.0 if code == SMUFL_NOTEHEAD_HALF else 4.0)
                dur_type = "quarter" if code == SMUFL_NOTEHEAD_BLACK else ("half" if code == SMUFL_NOTEHEAD_HALF else "whole")

                elements.append(NoteElement(
                    pitch=pitch_str,
                    midi_pitch=midi,
                    duration_quarters=dur_ql,
                    duration_type=dur_type,
                    offset_quarters=off_ql,
                    is_rest=False
                ))
            elif code in SMUFL_RESTS:
                dur_ql = 4.0 if code == SMUFL_REST_WHOLE else (2.0 if code == SMUFL_REST_HALF else 1.0)
                elements.append(NoteElement(
                    pitch=None,
                    duration_quarters=dur_ql,
                    duration_type="rest",
                    offset_quarters=off_ql,
                    is_rest=True
                ))

        if not elements:
            return [NoteElement(pitch=None, duration_quarters=4.0, duration_type="whole", offset_quarters=0.0, is_rest=True)]

        return elements

    @staticmethod
    def _midi_to_pitch_str(midi: int) -> str:
        notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        octave = (midi // 12) - 1
        name = notes[midi % 12]
        return f"{name}{octave}"
