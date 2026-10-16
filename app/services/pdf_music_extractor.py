from fractions import Fraction
import logging
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple, Any

import music21
from music21 import stream, note, chord, meter, tempo, clef, layout, metadata
import pymupdf

logger = logging.getLogger(__name__)

# SMuFL Codepoints used by FinaleMaestro, Bravura, MuseScore (Leland), Sibelius, Dorico
SMUFL_G_CLEF = 0xE050
SMUFL_F_CLEF = 0xE062
SMUFL_C_CLEF = 0xE05C

SMUFL_DIGITS = {0xE080 + i: str(i) for i in range(10)}

SMUFL_NOTEHEAD_WHOLE = 0xE0A2
SMUFL_NOTEHEAD_HALF = 0xE0A3
SMUFL_NOTEHEAD_BLACK = 0xE0A4
SMUFL_NOTEHEADS = {SMUFL_NOTEHEAD_WHOLE, SMUFL_NOTEHEAD_HALF, SMUFL_NOTEHEAD_BLACK}

SMUFL_AUG_DOT = 0xE1E7
SMUFL_FLAG_8TH_UP = 0xE240
SMUFL_FLAG_8TH_DOWN = 0xE241
SMUFL_FLAGS_8TH = {SMUFL_FLAG_8TH_UP, SMUFL_FLAG_8TH_DOWN}

SMUFL_FLAT = 0xE260
SMUFL_NATURAL = 0xE261
SMUFL_SHARP = 0xE262
SMUFL_ACCIDENTALS = {SMUFL_FLAT: -1, SMUFL_NATURAL: 0, SMUFL_SHARP: 1}

SMUFL_REST_WHOLE = 0xE4E3
SMUFL_REST_HALF = 0xE4E4
SMUFL_REST_QUARTER = 0xE4E5
SMUFL_REST_8TH = 0xE4E6
SMUFL_RESTS = {SMUFL_REST_WHOLE, SMUFL_REST_HALF, SMUFL_REST_QUARTER, SMUFL_REST_8TH}

# Diatonic pitch names from C
DIATONIC_STEPS = ["C", "D", "E", "F", "G", "A", "B"]

# Order of flats and sharps in standard key signatures
FLAT_ORDER = ["B", "E", "A", "D", "G", "C", "F"]
SHARP_ORDER = ["F", "C", "G", "D", "A", "E", "B"]


class PDFMusicExtractor:
    """
    Deterministic Digital PDF / SMuFL Vector Score Extractor.
    Directly parses vector staff lines, barlines, SMuFL music glyphs, measure numbers,
    multi-measure rests, time signatures, key signatures, tempos, and vocal/piano topology
    from digital sheet music PDFs (Finale, Dorico, MuseScore, Sibelius).
    """

    @classmethod
    def can_extract_vector_music(cls, pdf_path: Path) -> bool:
        """Returns True if the PDF contains embedded SMuFL / music font noteheads and vector staves."""
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
            logger.warning(f"Vector music check failed on {pdf_path}: {e}")
        return False

    @classmethod
    def extract_visual_skeleton(cls, pdf_path: Path) -> Dict[str, Any]:
        """
        Extracts a deterministic visual/structural skeleton from ANY PDF score (vector or scanned):
        - Header metadata (title, composer, subtitle)
        - Systems per page, staves per system, and exact staff [y_top, y_bot] coordinates
        - Barline counts and printed measure numbers / multi-measure rest spans per system
        - Lyric presence below each staff and Bottom-Up Piano vs. Vocal staff classification (Rule A1a)
        """
        try:
            doc = pymupdf.open(str(pdf_path))
            title, composer, subtitle = cls._extract_header_metadata(doc, pdf_path)
            page_count = len(doc)
            all_systems = []
            for p_idx, page in enumerate(doc):
                page_systems = cls._extract_page_systems(page, p_idx + 1)
                all_systems.extend(page_systems)
            doc.close()
        except Exception as e:
            logger.warning(f"Visual skeleton extraction failed on {pdf_path}: {e}")
            return {
                "title": pdf_path.stem.replace("_", " ").title(),
                "composer": "Unknown Composer",
                "subtitle": "",
                "page_count": 0,
                "total_systems": 0,
                "num_staves": 2,
                "has_piano": False,
                "total_measures": 0,
                "systems_blueprint": [],
                "measures": []
            }

        if not all_systems:
            return {
                "title": title,
                "composer": composer,
                "subtitle": subtitle,
                "page_count": page_count,
                "total_systems": 0,
                "num_staves": 2,
                "has_piano": False,
                "total_measures": 0,
                "systems_blueprint": [],
                "measures": []
            }

        max_staves = max(len(s["staves"]) for s in all_systems)
        # Determine if score has Piano accompaniment (Rule A1 / A1a):
        # True if any system has >= 3 staves where bottom staff has no lyrics, or explicit piano label
        has_piano = False
        for sys in all_systems:
            st_list = sys["staves"]
            if any("piano" in (st.get("label", "")).lower() or "organ" in (st.get("label", "")).lower() for st in st_list):
                has_piano = True
                break
            if len(st_list) >= 3 and not st_list[-1].get("has_lyrics", False):
                has_piano = True
                break

        systems_blueprint = []
        running_measure = 1
        for s_idx, sys in enumerate(all_systems):
            if sys.get("start_measure_num") is not None:
                running_measure = sys["start_measure_num"]
            m_start = running_measure
            bar_x = sys.get("bar_x", [])
            num_visual_bars = max(1, len(bar_x) - 1)
            sys_bars = 0
            for b_i in range(num_visual_bars):
                if b_i in sys.get("mm_ranges", {}):
                    r0, r1 = sys["mm_ranges"][b_i]
                    sys_bars += (r1 - r0 + 1)
                    running_measure = r1 + 1
                else:
                    sys_bars += 1
                    running_measure += 1
            m_end = m_start + max(1, sys_bars) - 1

            n_st = len(sys["staves"])
            if has_piano:
                if n_st >= 3:
                    n_vocal = n_st - 2
                    n_piano = 2
                elif n_st == 2:
                    # Check if 2-staff system in accompanied score has lyrics (vocal) or not (piano intro/interlude)
                    if any(st.get("has_lyrics", False) for st in sys["staves"]):
                        n_vocal = 2
                        n_piano = 0
                    else:
                        n_vocal = 0
                        n_piano = 2
                else:
                    n_vocal = 1 if sys["staves"][0].get("has_lyrics", False) else 0
                    n_piano = 1 - n_vocal
            else:
                n_vocal = n_st
                n_piano = 0

            staves_detail = []
            for st_i, st in enumerate(sys["staves"]):
                is_pno = has_piano and (st_i >= n_vocal)
                if is_pno:
                    role = "piano_rh" if (st_i == n_vocal) else "piano_lh"
                    targets = ["Piano"]
                else:
                    role = "vocal"
                    if n_vocal == 1:
                        targets = ["T1", "T2", "Bar1", "Bar2", "B1", "B2"] if st.get("clef") == "bass" else ["S1", "S2", "A1", "A2"]
                    elif n_vocal == 2:
                        targets = ["S1", "S2", "A1", "A2"] if st_i == 0 else ["T1", "T2", "Bar1", "Bar2", "B1", "B2"]
                    elif n_vocal == 3:
                        targets = [["S1", "S2"], ["A1", "A2"], ["T1", "T2", "Bar1", "Bar2", "B1", "B2"]][min(st_i, 2)]
                    else:
                        targets = [["S1", "S2"], ["A1", "A2"], ["T1", "T2"], ["Bar1", "Bar2", "B1", "B2"]][min(st_i, 3)]
                staves_detail.append({
                    "staff_index": st_i,
                    "y_top": st["y_top"],
                    "y_bot": st["y_bot"],
                    "clef": st.get("clef", "treble"),
                    "has_lyrics": st.get("has_lyrics", False),
                    "role": role,
                    "targets": targets
                })

            systems_blueprint.append({
                "system_index": s_idx + 1,
                "page_num": sys["page_num"],
                "y_top": sys["y_top"],
                "y_bot": sys["y_bot"],
                "x_left": sys["x_left"],
                "x_right": sys["x_right"],
                "num_staves": n_st,
                "vocal_staves": n_vocal,
                "piano_staves": n_piano,
                "measure_start": m_start,
                "measure_end": m_end,
                "measure_count": m_end - m_start + 1,
                "staves_detail": staves_detail
            })

        total_measures = systems_blueprint[-1]["measure_end"] if systems_blueprint else 0
        return {
            "title": title,
            "composer": composer,
            "subtitle": subtitle,
            "page_count": page_count,
            "total_systems": len(all_systems),
            "num_staves": max_staves,
            "has_piano": has_piano,
            "total_measures": total_measures,
            "systems_blueprint": systems_blueprint,
            "measures": []
        }

    @classmethod
    def extract_to_musicxml(cls, pdf_path: Path, output_xml_path: Path) -> Tuple[Path, Dict[str, Any]]:
        """
        Extracts the complete multi-staff score from a vector PDF and writes it to MusicXML.
        Also returns a rich structural telemetry dictionary for the LLM / Audit pipeline.
        """
        doc = pymupdf.open(str(pdf_path))
        title, composer, subtitle = cls._extract_header_metadata(doc, pdf_path)

        # Collect systems across all pages
        all_systems = []
        for p_idx, page in enumerate(doc):
            page_systems = cls._extract_page_systems(page, p_idx + 1)
            all_systems.extend(page_systems)

        doc.close()

        if not all_systems:
            raise ValueError(f"No musical systems detected in {pdf_path.name}")

        skeleton = cls.extract_visual_skeleton(pdf_path)
        # Build unified MusicXML Score
        score, telemetry = cls._build_score_from_systems(title, composer, subtitle, all_systems)
        telemetry["has_piano"] = skeleton.get("has_piano", False)
        telemetry["systems_blueprint"] = skeleton.get("systems_blueprint", [])
        output_xml_path.parent.mkdir(parents=True, exist_ok=True)
        score.write("musicxml", fp=str(output_xml_path))
        logger.info(
            f"PDFMusicExtractor exported '{title}' ({composer}) with "
            f"{telemetry['total_measures']} measures and {telemetry['total_notes']} noteheads to {output_xml_path}"
        )
        return output_xml_path, telemetry

    @classmethod
    def _extract_header_metadata(cls, doc: pymupdf.Document, pdf_path: Path) -> Tuple[str, str, str]:
        title = pdf_path.stem.replace("_", " ").title()
        composer = "Unknown Composer"
        subtitle = ""

        if len(doc) == 0:
            return title, composer, subtitle

        p0 = doc[0]
        spans = []
        for b in p0.get_text("dict").get("blocks", []):
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    txt = s["text"].strip()
                    if not txt or "Maestro" in s["font"]:
                        continue
                    # Ignore SMuFL Private Use Area characters
                    if any(0xE000 <= ord(ch) <= 0xF8FF for ch in txt):
                        continue
                    x0, y0, x1, y1 = s["bbox"]
                    if y0 < 125:
                        spans.append({
                            "text": txt,
                            "size": s["size"],
                            "x0": x0,
                            "y0": y0,
                            "x_center": (x0 + x1) / 2.0
                        })

        if spans:
            # Largest centered text near top is the Title
            centered = [
                sp for sp in spans
                if 150 < sp["x_center"] < 460 and sp["text"].lower() not in ("choir", "piano", "vocal score")
            ]
            if centered:
                best_title = max(centered, key=lambda x: x["size"])
                title = best_title["text"]
                # Subtitle below title
                subs = [
                    sp["text"] for sp in centered
                    if sp is not best_title and sp["y0"] > best_title["y0"]
                ]
                if subs:
                    subtitle = " — ".join(subs)

            # Right-aligned text in header (x0 > 350) is Composer / Arranger
            right_spans = [sp for sp in spans if sp["x0"] > 350 and sp["text"] != title]
            if right_spans:
                composer = " / ".join(sp["text"] for sp in sorted(right_spans, key=lambda x: x["y0"]))

        return title, composer, subtitle

    @classmethod
    def _extract_page_systems(cls, page: pymupdf.Page, page_num: int) -> List[Dict[str, Any]]:
        drawings = page.get_drawings()

        # 1. Find horizontal staff lines (width > 150pt, height < 2pt)
        horiz_lines = []
        for d in drawings:
            r = d["rect"]
            w = r.x1 - r.x0
            h = r.y1 - r.y0
            if w > 150 and h < 2.0:
                horiz_lines.append((round((r.y0 + r.y1) / 2.0, 2), round(r.x0, 1), round(r.x1, 1)))

        # Deduplicate by Y coordinate (within 0.6pt)
        horiz_lines.sort(key=lambda x: x[0])
        unique_lines = []
        for y, x0, x1 in horiz_lines:
            if not unique_lines or abs(y - unique_lines[-1][0]) > 0.8:
                unique_lines.append([y, x0, x1])
            else:
                unique_lines[-1][1] = min(unique_lines[-1][1], x0)
                unique_lines[-1][2] = max(unique_lines[-1][2], x1)

        # Group into 5-line staves
        staves = []
        cur = []
        for line in unique_lines:
            if not cur or (line[0] - cur[-1][0]) < 10.0:
                cur.append(line)
            else:
                if len(cur) == 5:
                    staves.append({
                        "lines": [c[0] for c in cur],
                        "y_top": cur[0][0],
                        "y_bot": cur[-1][0],
                        "x_left": min(c[1] for c in cur),
                        "x_right": max(c[2] for c in cur),
                        "space": (cur[-1][0] - cur[0][0]) / 4.0
                    })
                cur = [line]
        if len(cur) == 5:
            staves.append({
                "lines": [c[0] for c in cur],
                "y_top": cur[0][0],
                "y_bot": cur[-1][0],
                "x_left": min(c[1] for c in cur),
                "x_right": max(c[2] for c in cur),
                "space": (cur[-1][0] - cur[0][0]) / 4.0
            })

        if not staves:
            return []

        # 2. Group staves into systems using left/right-edge system connectors
        systems = []
        idx = 0
        while idx < len(staves):
            s_top = staves[idx]
            group = [s_top]
            next_idx = idx + 1
            while next_idx < len(staves):
                prev_st = group[-1]
                cand = staves[next_idx]
                connected = False
                for d in drawings:
                    r = d["rect"]
                    if (r.x1 - r.x0) < 5.0 and (
                        abs(r.x0 - s_top["x_left"]) < 6.0 or abs(r.x0 - s_top["x_right"]) < 6.0
                    ):
                        if r.y0 <= prev_st["y_bot"] + 2.0 and r.y1 >= cand["y_bot"] - 2.0:
                            connected = True
                            break
                if connected:
                    group.append(cand)
                    next_idx += 1
                else:
                    break
            systems.append({
                "page_num": page_num,
                "staves": group,
                "y_top": group[0]["y_top"],
                "y_bot": group[-1]["y_bot"],
                "x_left": group[0]["x_left"],
                "x_right": group[0]["x_right"]
            })
            idx = next_idx

        # 3. Extract all text spans and SMuFL glyphs on this page
        text_spans = []
        smufl_chars = []
        for b in page.get_text("rawdict").get("blocks", []):
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    font_name = s.get("font", "")
                    chars = s.get("chars", [])
                    if "Maestro" in font_name or any(0xE000 <= ord(c["c"]) <= 0xF8FF for c in chars):
                        for c in chars:
                            code = ord(c["c"])
                            if code > 0x20:
                                smufl_chars.append({
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
                                "font": font_name,
                                "size": s.get("size", 10.0),
                                "bbox": s["bbox"],
                                "x": float(s["bbox"][0]),
                                "y": float(s["bbox"][1])
                            })

        non_lyric_tokens = {
            "p", "mp", "mf", "f", "ff", "pp", "cresc.", "cresc", "dim.", "dim",
            "rit.", "rit", "rall.", "rall", "a tempo", "tempo primo", "unis.", "div."
        }

        # 4. Populate each system with barlines, measure numbers, multi-measure rests, tempos, and glyphs
        for sys in systems:
            y0_ref = sys["staves"][0]["y_top"]
            y1_ref = sys["staves"][0]["y_bot"]

            # Barlines on the top staff of the system (strictly matching staff top and bottom lines)
            top_staff_bars = []
            for d in drawings:
                r = d["rect"]
                if (r.x1 - r.x0) < 3.5 and abs(r.y0 - y0_ref) < 0.9 and abs(r.y1 - y1_ref) < 0.9:
                    top_staff_bars.append(round((r.x0 + r.x1) / 2.0, 2))

            if len(sys["staves"]) >= 2:
                yb0 = sys["staves"][-1]["y_top"]
                yb1 = sys["staves"][-1]["y_bot"]
                bot_staff_bars = []
                for d in drawings:
                    r = d["rect"]
                    if (r.x1 - r.x0) < 3.5 and abs(r.y0 - yb0) < 0.9 and abs(r.y1 - yb1) < 0.9:
                        bot_staff_bars.append(round((r.x0 + r.x1) / 2.0, 2))
                # Keep only barlines present at the same X on both top and bottom staves
                verified_bars = [
                    bx for bx in top_staff_bars
                    if any(abs(bx - bbx) < 1.5 for bbx in bot_staff_bars)
                ]
            else:
                verified_bars = top_staff_bars

            raw_bars = [sys["x_left"]] + verified_bars + [sys["x_right"]]
            raw_bars.sort()

            merged_bars = []
            for bx in raw_bars:
                if not merged_bars or (bx - merged_bars[-1]) > 8.0:
                    merged_bars.append(bx)
            sys["bar_x"] = merged_bars

            # System starting measure number (printed in box above top-left of system)
            sys_m_num = None
            for sp in text_spans:
                if re.match(r"^\d+$", sp["text"]) and sp["x"] < 100.0:
                    if (y0_ref - 35.0) <= sp["y"] <= (y0_ref + 5.0):
                        sys_m_num = int(sp["text"])
                        break
            sys["start_measure_num"] = sys_m_num

            # Multi-measure rest ranges like [16-42] associated with this system
            mm_ranges = {}
            for sp in text_spans:
                m_rng = re.match(r"^\[(\d+)-(\d+)\]$", sp["text"])
                if m_rng and (sys["y_top"] - 25.0) <= sp["y"] <= (sys["y_bot"] + 30.0):
                    r_start, r_end = int(m_rng.group(1)), int(m_rng.group(2))
                    x_mid = (sp["bbox"][0] + sp["bbox"][2]) / 2.0
                    # Find which bar interval [bar_x[i], bar_x[i+1]] contains x_mid
                    for b_i in range(len(merged_bars) - 1):
                        if merged_bars[b_i] - 5.0 <= x_mid <= merged_bars[b_i + 1] + 5.0:
                            mm_ranges[b_i] = (r_start, r_end)
                            break
            sys["mm_ranges"] = mm_ranges

            # Tempo markings above this system
            tempos = []
            for sp in text_spans:
                if (y0_ref - 48.0) <= sp["y"] <= (y0_ref + 2.0):
                    m_bpm = re.search(r"=\s*(\d+)", sp["text"])
                    if m_bpm:
                        tempos.append((sp["x"], float(m_bpm.group(1)), sp["text"]))
                    elif "tempo primo" in sp["text"].lower():
                        tempos.append((sp["x"], 138.0, "Tempo primo"))
            sys["tempos"] = tempos

            # Assign SMuFL glyphs, clef, label, and lyric detection to each staff in the system
            for st_idx, st in enumerate(sys["staves"]):
                st_top = st["y_top"] - 26.0
                st_bot = st["y_bot"] + 28.0
                st["glyphs"] = [
                    g for g in smufl_chars
                    if st_top <= g["y"] <= st_bot
                ]
                st_clef = "bass" if st_idx == len(sys["staves"]) - 1 else "treble"
                for g in st["glyphs"]:
                    if g["x"] < sys["x_left"] + 45.0:
                        if g["code"] == SMUFL_G_CLEF:
                            st_clef = "treble"
                        elif g["code"] == SMUFL_F_CLEF:
                            st_clef = "bass"
                st["clef"] = st_clef

                # Detect left-margin staff label
                labels = [
                    sp["text"] for sp in text_spans
                    if sp["x"] < sys["x_left"] - 2.0 and (st["y_top"] - 8.0) <= sp["y"] <= (st["y_bot"] + 8.0)
                ]
                st["label"] = " ".join(labels)

                # Detect lyrics below the staff (between y_bot - 2 and y_bot + 24, before next staff)
                next_y_top = sys["staves"][st_idx + 1]["y_top"] - 4.0 if (st_idx + 1) < len(sys["staves"]) else st["y_bot"] + 24.0
                lyric_y_max = min(st["y_bot"] + 24.0, next_y_top)
                lyric_words = [
                    sp["text"] for sp in text_spans
                    if sp["x"] >= sys["x_left"]
                    and (st["y_bot"] - 2.0) <= sp["y"] <= lyric_y_max
                    and sp["text"].lower() not in non_lyric_tokens
                    and not re.match(r"^\[?\d+(-\d+)?\]?$", sp["text"])
                ]
                st["has_lyrics"] = len(lyric_words) >= 2

        return systems

    @classmethod
    def _build_score_from_systems(
        cls,
        title: str,
        composer: str,
        subtitle: str,
        systems: List[Dict[str, Any]]
    ) -> Tuple[music21.stream.Score, Dict[str, Any]]:
        max_staves = max(len(s["staves"]) for s in systems)
        has_piano = any(
            len(s["staves"]) >= 3 and not s["staves"][-1].get("has_lyrics", False)
            for s in systems
        ) or any(
            "piano" in (st.get("label", "")).lower() or "organ" in (st.get("label", "")).lower()
            for s in systems for st in s["staves"]
        )

        score = stream.Score()
        score.metadata = metadata.Metadata()
        score.metadata.title = title
        score.metadata.composer = composer

        parts: List[music21.stream.Part] = []
        if not has_piano and max_staves <= 2:
            num_parts = 2
            p_sa = stream.Part(id="Soprano_Alto")
            p_sa.partName = "Soprano / Alto"
            p_sa.partAbbreviation = "SA"
            p_tb = stream.Part(id="Tenor_Bass")
            p_tb.partName = "Tenor / Bass"
            p_tb.partAbbreviation = "TB"
            parts = [p_sa, p_tb]
            vocal_group = layout.StaffGroup(parts, symbol="bracket", name="Choir")
            score.append(vocal_group)
        elif has_piano:
            max_vocal = max(2, max_staves - 2)
            vocal_parts = []
            if max_vocal == 2:
                p_sa = stream.Part(id="Soprano_Alto")
                p_sa.partName = "Soprano / Alto"
                p_sa.partAbbreviation = "SA"
                p_tb = stream.Part(id="Tenor_Bass")
                p_tb.partName = "Tenor / Bass"
                p_tb.partAbbreviation = "TB"
                vocal_parts = [p_sa, p_tb]
            else:
                names = [("Soprano", "S"), ("Alto", "A"), ("Tenor", "T"), ("Bass", "B")]
                for idx in range(max_vocal):
                    nm, ab = names[idx] if idx < len(names) else (f"Vocal {idx+1}", f"V{idx+1}")
                    vp = stream.Part(id=nm)
                    vp.partName = nm
                    vp.partAbbreviation = ab
                    vocal_parts.append(vp)
            p_rh = stream.Part(id="Piano_RH")
            p_rh.partName = "Piano Right Hand"
            p_lh = stream.Part(id="Piano_LH")
            p_lh.partName = "Piano Left Hand"
            piano_parts = [p_rh, p_lh]
            parts = vocal_parts + piano_parts
            num_parts = len(parts)
            score.append(layout.StaffGroup(vocal_parts, symbol="bracket", name="Choir"))
            score.append(layout.StaffGroup(piano_parts, symbol="brace", name="Piano"))
        else:
            num_parts = max(2, max_staves)
            for idx in range(num_parts):
                p = stream.Part(id=f"Part_{idx+1}")
                p.partName = f"Staff {idx+1}"
                parts.append(p)
            vocal_group = layout.StaffGroup(parts, symbol="bracket", name="Choir")
            score.append(vocal_group)

        # Running musical state across systems
        current_measure_num = 1
        current_ts_str = "6/8"
        current_bar_ql = Fraction(3, 1)
        current_tempo_bpm = 138.0  # Dotted quarter = 92 -> 138 quarter BPM
        current_fifths = 0         # Key signature fifths (- flat, + sharp)
        staff_clefs = ["treble", "bass"] + ["treble"] * max(0, num_parts - 2)

        total_extracted_notes = 0
        measure_summary = []

        for sys_idx, sys in enumerate(systems):
            if sys["start_measure_num"] is not None:
                current_measure_num = sys["start_measure_num"]

            bar_x = sys["bar_x"]
            num_visual_bars = len(bar_x) - 1
            sys_staves = sys["staves"]

            # Detect clefs on this system's staves
            for st_i, st in enumerate(sys_staves):
                st_clef = st.get("clef", "bass" if st_i == len(sys_staves) - 1 else "treble")
                for g in st["glyphs"]:
                    if g["x"] < bar_x[0] + 45.0:
                        if g["code"] == SMUFL_G_CLEF:
                            st_clef = "treble"
                        elif g["code"] == SMUFL_F_CLEF:
                            st_clef = "bass"
                st["clef"] = st_clef
                if st_i < len(staff_clefs):
                    staff_clefs[st_i] = st_clef

            # Map system staves to canonical part indices (Bottom-Up Piano Anchor per Rule A1a)
            part_to_staff_map: Dict[int, Dict[str, Any]] = {}
            if not has_piano:
                for p_i in range(min(len(parts), len(sys_staves))):
                    part_to_staff_map[p_i] = sys_staves[p_i]
            else:
                n_vocal_parts = len(parts) - 2
                n_sys = len(sys_staves)
                if n_sys >= 3:
                    # Bottom 2 staves are Piano RH and Piano LH
                    part_to_staff_map[n_vocal_parts] = sys_staves[-2]
                    part_to_staff_map[n_vocal_parts + 1] = sys_staves[-1]
                    vocal_sys_staves = sys_staves[:-2]
                elif n_sys == 2:
                    if any(st.get("has_lyrics", False) for st in sys_staves):
                        vocal_sys_staves = sys_staves
                    else:
                        part_to_staff_map[n_vocal_parts] = sys_staves[0]
                        part_to_staff_map[n_vocal_parts + 1] = sys_staves[1]
                        vocal_sys_staves = []
                else:
                    if sys_staves[0].get("has_lyrics", False):
                        vocal_sys_staves = sys_staves
                    else:
                        part_to_staff_map[n_vocal_parts] = sys_staves[0]
                        vocal_sys_staves = []

                # Map vocal_sys_staves onto canonical vocal parts [0 .. n_vocal_parts - 1]
                nv = len(vocal_sys_staves)
                if nv == 1:
                    vst = vocal_sys_staves[0]
                    if vst.get("clef") == "bass":
                        # Route to male vocal slots (bottom half of vocal parts)
                        for vp_i in range(n_vocal_parts // 2, n_vocal_parts):
                            part_to_staff_map[vp_i] = vst
                    else:
                        # Route to female vocal slots (top half of vocal parts)
                        for vp_i in range(0, max(1, n_vocal_parts // 2)):
                            part_to_staff_map[vp_i] = vst
                elif nv == 2 and n_vocal_parts >= 4:
                    # 2 vocal staves (SA + TB) mapped onto 4 canonical vocal parts (S, A, T, B)
                    part_to_staff_map[0] = vocal_sys_staves[0]
                    part_to_staff_map[1] = vocal_sys_staves[0]
                    part_to_staff_map[2] = vocal_sys_staves[1]
                    part_to_staff_map[3] = vocal_sys_staves[1]
                else:
                    for vp_i in range(min(n_vocal_parts, nv)):
                        part_to_staff_map[vp_i] = vocal_sys_staves[vp_i]

            for b_i in range(num_visual_bars):
                x0 = bar_x[b_i]
                x1 = bar_x[b_i + 1]

                # Check for time signature changes inside or at the start of this visual bar
                ts_found = cls._detect_time_signature_in_bar(sys_staves[0]["glyphs"], x0, x1, b_i == 0)
                if ts_found:
                    current_ts_str = ts_found
                    current_bar_ql = Fraction(meter.TimeSignature(current_ts_str).barDuration.quarterLength)

                # Check for tempo changes near x0
                for tx, tbpm, tlabel in sys["tempos"]:
                    if (x0 - 25.0) <= tx <= (x1 + 10.0) or (b_i == 0 and tx < x1):
                        # Convert dotted-quarter BPM to quarter-note BPM in compound meters (6/8, 12/8)
                        if current_ts_str.endswith("/8") and tbpm < 130.0:
                            current_tempo_bpm = round(tbpm * 1.5, 1)
                        else:
                            current_tempo_bpm = tbpm

                # Check for key signature at start of bar (before first notehead)
                ks_fifths = cls._detect_key_signature_in_bar(sys_staves[0]["glyphs"], x0, x1, b_i == 0)
                if ks_fifths is not None:
                    current_fifths = ks_fifths

                # Check if this visual bar is a multi-measure rest range [start-end]
                if b_i in sys["mm_ranges"]:
                    r_start, r_end = sys["mm_ranges"][b_i]
                    for m_num in range(r_start, r_end + 1):
                        prev_ts_emitted = measure_summary[-1]["ts"] if measure_summary else None
                        prev_tm_emitted = measure_summary[-1]["tempo_bpm"] if measure_summary else None
                        for p_i, p in enumerate(parts):
                            m = stream.Measure(number=m_num)
                            if m_num == 1 or current_ts_str != prev_ts_emitted:
                                m.timeSignature = meter.TimeSignature(current_ts_str)
                            if m_num == 1 or current_tempo_bpm != prev_tm_emitted:
                                m.insert(0, tempo.MetronomeMark(number=current_tempo_bpm))
                            m.append(note.Rest(quarterLength=current_bar_ql))
                            p.append(m)
                        measure_summary.append({
                            "measure": m_num,
                            "ts": current_ts_str,
                            "tempo_bpm": current_tempo_bpm,
                            "fifths": current_fifths,
                            "type": "multi_measure_rest"
                        })
                    current_measure_num = r_end + 1
                    continue

                # Skip narrow key/time-signature change preamble boxes that have no noteheads or rests
                has_any_notes_or_rests = any(
                    (x0 + 2.0) <= g["x"] <= (x1 - 2.0) and g["code"] in (SMUFL_NOTEHEADS | SMUFL_RESTS)
                    for st in sys_staves for g in st["glyphs"]
                )
                if not has_any_notes_or_rests and (x1 - x0) < 75.0:
                    continue

                # Also prevent overflowing into the next system's starting measure number
                if (sys_idx + 1) < len(systems) and systems[sys_idx + 1]["start_measure_num"] is not None:
                    if current_measure_num >= systems[sys_idx + 1]["start_measure_num"]:
                        continue

                # Single measure: extract notes and chords for each canonical part
                m_num = current_measure_num
                bar_note_count = 0
                prev_ts_emitted = measure_summary[-1]["ts"] if measure_summary else None
                prev_tm_emitted = measure_summary[-1]["tempo_bpm"] if measure_summary else None

                for p_i, p in enumerate(parts):
                    m = stream.Measure(number=m_num)
                    mapped_st = part_to_staff_map.get(p_i)
                    part_clef = mapped_st.get("clef", "treble") if mapped_st else (
                        staff_clefs[p_i] if p_i < len(staff_clefs) else "treble"
                    )
                    if m_num == 1:
                        m.insert(0, clef.BassClef() if part_clef == "bass" else clef.TrebleClef())
                    if m_num == 1 or current_ts_str != prev_ts_emitted:
                        m.timeSignature = meter.TimeSignature(current_ts_str)
                    if m_num == 1 or current_tempo_bpm != prev_tm_emitted:
                        m.insert(0, tempo.MetronomeMark(number=current_tempo_bpm))

                    if mapped_st is not None:
                        extracted_elems = cls._extract_measure_elements_on_staff(
                            st=mapped_st,
                            x0=x0,
                            x1=x1,
                            is_first_bar_of_sys=(b_i == 0),
                            clef_type=part_clef,
                            fifths=current_fifths,
                            bar_ql=current_bar_ql
                        )
                        if not extracted_elems:
                            m.append(note.Rest(quarterLength=current_bar_ql))
                        else:
                            for off_ql, elem in extracted_elems:
                                m.insert(float(off_ql), elem)
                                if isinstance(elem, (note.Note, chord.Chord)):
                                    bar_note_count += 1
                                    total_extracted_notes += 1
                    else:
                        m.append(note.Rest(quarterLength=current_bar_ql))

                    p.append(m)

                measure_summary.append({
                    "measure": m_num,
                    "ts": current_ts_str,
                    "tempo_bpm": current_tempo_bpm,
                    "fifths": current_fifths,
                    "type": "active" if bar_note_count > 0 else "rest",
                    "events": bar_note_count
                })
                current_measure_num += 1

        for p in parts:
            score.append(p)

        telemetry = {
            "title": title,
            "composer": composer,
            "subtitle": subtitle,
            "total_systems": len(systems),
            "num_staves": num_parts,
            "has_piano": has_piano,
            "total_measures": len(measure_summary),
            "total_notes": total_extracted_notes,
            "measures": measure_summary
        }
        return score, telemetry

    @classmethod
    def _detect_time_signature_in_bar(
        cls,
        glyphs: List[Dict[str, Any]],
        x0: float,
        x1: float,
        is_first_bar: bool
    ) -> Optional[str]:
        """Detects SMuFL time signature numerator/denominator in the header region of a bar."""
        # Ignore courtesy time signatures at the very right end of a system
        search_x1 = min(x1 - 12.0, x0 + 65.0)
        ts_digits = [
            g for g in glyphs
            if g["code"] in SMUFL_DIGITS and (x0 - 2.0) <= g["x"] <= search_x1
        ]
        if len(ts_digits) < 2:
            return None

        # Split into upper row (numerator) and lower row (denominator) by Y coordinate
        ys = [g["y"] for g in ts_digits]
        y_min, y_max = min(ys), max(ys)
        if (y_max - y_min) < 4.0:
            return None

        y_mid = (y_min + y_max) / 2.0
        upper = sorted([g for g in ts_digits if g["y"] < y_mid], key=lambda x: x["x"])
        lower = sorted([g for g in ts_digits if g["y"] >= y_mid], key=lambda x: x["x"])
        if not upper or not lower:
            return None

        num_str = "".join(SMUFL_DIGITS[g["code"]] for g in upper)
        den_str = "".join(SMUFL_DIGITS[g["code"]] for g in lower)
        candidate = f"{num_str}/{den_str}"
        if candidate in ("6/8", "12/8", "9/8", "2/4", "3/4", "4/4", "2/2", "3/2"):
            return candidate
        return None

    @classmethod
    def _detect_key_signature_in_bar(
        cls,
        glyphs: List[Dict[str, Any]],
        x0: float,
        x1: float,
        is_first_bar: bool
    ) -> Optional[int]:
        """Counts key signature flats/sharps appearing before the first notehead or rest in a bar."""
        first_note_x = x0 + 55.0
        for g in glyphs:
            if (x0 + 2.0) <= g["x"] <= x1 and g["code"] in (SMUFL_NOTEHEADS | SMUFL_RESTS):
                first_note_x = min(first_note_x, g["x"] - 8.0)

        if first_note_x <= x0 + 4.0:
            return None

        header_acc = [
            g for g in glyphs
            if (x0 + 1.0) <= g["x"] <= first_note_x and g["code"] in (SMUFL_FLAT, SMUFL_SHARP, SMUFL_NATURAL)
        ]
        if not header_acc:
            return 0 if is_first_bar else None

        flats = sum(1 for g in header_acc if g["code"] == SMUFL_FLAT)
        sharps = sum(1 for g in header_acc if g["code"] == SMUFL_SHARP)
        if flats > 0 and sharps == 0:
            return -min(flats, 7)
        elif sharps > 0 and flats == 0:
            return min(sharps, 7)
        elif flats == 0 and sharps == 0:
            return 0
        return None

    @classmethod
    def _extract_measure_elements_on_staff(
        cls,
        st: Dict[str, Any],
        x0: float,
        x1: float,
        is_first_bar_of_sys: bool,
        clef_type: str,
        fifths: int,
        bar_ql: Fraction
    ) -> List[Tuple[Fraction, music21.note.GeneralNote]]:
        glyphs = [g for g in st["glyphs"] if (x0 + 2.0) <= g["x"] <= (x1 - 2.0)]
        noteheads = sorted(
            [g for g in glyphs if g["code"] in SMUFL_NOTEHEADS],
            key=lambda g: (g["x"], g["y"])
        )
        if not noteheads:
            return []

        dots = [g for g in glyphs if g["code"] == SMUFL_AUG_DOT]
        flags = [g for g in glyphs if g["code"] in SMUFL_FLAGS_8TH]
        accidentals = [g for g in glyphs if g["code"] in SMUFL_ACCIDENTALS]

        # Key signature pitch alterations map
        ks_alter: Dict[str, int] = {step: 0 for step in DIATONIC_STEPS}
        if fifths < 0:
            for i in range(abs(fifths)):
                ks_alter[FLAT_ORDER[i]] = -1
        elif fifths > 0:
            for i in range(fifths):
                ks_alter[SHARP_ORDER[i]] = 1

        # Track active accidentals within the measure by (step, octave)
        measure_alter: Dict[Tuple[str, int], int] = {}

        # Group simultaneous noteheads into vertical columns (dx <= 4.5pt)
        columns: List[List[Dict[str, Any]]] = []
        for nh in noteheads:
            if not columns or (nh["x"] - columns[-1][0]["x"]) > 4.5:
                columns.append([nh])
            else:
                columns[-1].append(nh)

        # Determine raw durations and pitches for each column
        col_events = []
        y_bot = st["y_bot"]
        half_space = st["space"] / 2.0

        for col in columns:
            col_x = sum(n["x"] for n in col) / len(col)
            # Determine base rhythmic duration from notehead type, dots, and flags
            codes = {n["code"] for n in col}
            has_dot = any(
                0.5 <= (d["x"] - n["x"]) <= 14.0 and abs(d["y"] - n["y"]) <= 4.8
                for n in col for d in dots
            )
            has_flag = any(
                -4.0 <= (f["x"] - n["x"]) <= 11.0 and abs(f["y"] - n["y"]) <= 28.0
                for n in col for f in flags
            )

            if SMUFL_NOTEHEAD_WHOLE in codes:
                dur_ql = Fraction(6, 1) if (has_dot or bar_ql == Fraction(6, 1)) else min(Fraction(4, 1), bar_ql)
            elif SMUFL_NOTEHEAD_HALF in codes:
                dur_ql = Fraction(3, 1) if has_dot else Fraction(2, 1)
            else:
                if has_dot:
                    dur_ql = Fraction(3, 2)  # Dotted quarter = 1.5 QL
                elif has_flag:
                    dur_ql = Fraction(1, 2)  # Eighth note = 0.5 QL
                else:
                    dur_ql = Fraction(1, 1)  # Quarter note (or beamed 8th refined below)

            # Calculate pitches for all noteheads in this column
            pitches = []
            for n in col:
                steps_from_bot = int(round((y_bot - n["y"]) / half_space))
                if clef_type == "treble":
                    # Bottom line E4 -> index 2 in DIATONIC_STEPS, octave 4
                    abs_step = 4 * 7 + 2 + steps_from_bot
                else:
                    # Bass clef: Bottom line G2 -> index 4 in DIATONIC_STEPS, octave 2
                    abs_step = 2 * 7 + 4 + steps_from_bot

                octave = abs_step // 7
                step_name = DIATONIC_STEPS[abs_step % 7]

                # Check for inline accidental immediately left of this notehead (2pt..13pt)
                inline_acc = None
                for acc in accidentals:
                    if 1.5 <= (n["x"] - acc["x"]) <= 13.5 and abs(n["y"] - acc["y"]) <= 2.4:
                        inline_acc = SMUFL_ACCIDENTALS[acc["code"]]
                        break

                if inline_acc is not None:
                    measure_alter[(step_name, octave)] = inline_acc
                    alter = inline_acc
                elif (step_name, octave) in measure_alter:
                    alter = measure_alter[(step_name, octave)]
                else:
                    alter = ks_alter[step_name]

                acc_str = "-" if alter == -1 else ("#" if alter == 1 else "")
                pitches.append(f"{step_name}{acc_str}{octave}")

            # Deduplicate identical pitches while preserving bottom-to-top sort
            unique_pitches = list(dict.fromkeys(pitches))
            col_events.append({
                "x": col_x,
                "dur_ql": dur_ql,
                "has_dot": has_dot,
                "has_flag": has_flag,
                "is_black": SMUFL_NOTEHEAD_BLACK in codes,
                "pitches": unique_pitches
            })

        # Refine beamed eighth notes when total duration exceeds bar_ql
        total_ql = sum(ev["dur_ql"] for ev in col_events)
        if total_ql > bar_ql:
            # Unflagged, undotted black noteheads that are beamed eighth notes (0.5 QL)
            for ev in col_events:
                if total_ql <= bar_ql:
                    break
                if ev["is_black"] and not ev["has_dot"] and not ev["has_flag"] and ev["dur_ql"] == Fraction(1, 1):
                    ev["dur_ql"] = Fraction(1, 2)
                    total_ql -= Fraction(1, 2)

        # Build sequentially offset Note / Chord objects clamped to bar_ql
        results: List[Tuple[Fraction, music21.note.GeneralNote]] = []
        cur_offset = Fraction(0)
        for ev in col_events:
            if cur_offset >= bar_ql:
                break
            dur = min(ev["dur_ql"], bar_ql - cur_offset)
            if dur <= 0:
                break
            if len(ev["pitches"]) == 1:
                el = note.Note(ev["pitches"][0], quarterLength=dur)
            else:
                el = chord.Chord(ev["pitches"], quarterLength=dur)
            results.append((cur_offset, el))
            cur_offset += dur

        return results
