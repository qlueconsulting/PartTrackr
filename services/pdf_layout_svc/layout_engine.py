import os
import re
from collections import Counter
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
import pymupdf
import numpy as np

from common.learning_store import LearningManager, ScoreStyleFingerprint

logger = logging.getLogger("pdf_layout_svc")


class PDFLayoutEngine:
    """
    Renders PDF pages to 300 DPI high-resolution PNGs, detects systems,
    staves, barlines, brackets, measure boxes, and produces cropped measure images.
    Supports both digital vector PDFs and scanned/raster sheet music PDFs.
    """

    @classmethod
    def process_pdf(
        cls,
        pdf_path: Path,
        output_dir: Path,
        dpi: int = 300,
        score_hints: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        crops_dir = output_dir / "crops"
        crops_dir.mkdir(parents=True, exist_ok=True)

        doc = pymupdf.open(str(pdf_path))
        page_count = len(doc)
        title, composer, subtitle = cls._extract_metadata(doc, pdf_path)

        pages_data = []
        all_systems_blueprint = []
        global_system_idx = 1
        global_measure_num = 1

        for p_idx in range(page_count):
            page = doc[p_idx]
            page_num = p_idx + 1

            # 1. Render high-res PNG at specified DPI
            pix = page.get_pixmap(dpi=dpi)
            page_png_path = output_dir / f"page_{page_num}.png"
            pix.save(str(page_png_path))

            page_w_pt = page.rect.width
            page_h_pt = page.rect.height

            # 2. Extract page systems, staff lines, and barlines in point coordinates
            systems = cls._extract_page_systems(page, page_num, score_hints=score_hints)

            page_systems_data = []
            for sys in systems:
                sys_idx = global_system_idx
                global_system_idx += 1

                # Starting measure override if printed in score
                if sys.get("start_measure_num") is not None and sys["start_measure_num"] >= global_measure_num:
                    global_measure_num = sys["start_measure_num"]

                m_start = global_measure_num
                bar_x = sys["bar_x"]
                num_bars = max(1, len(bar_x) - 1)

                # Crop system image from page PNG
                sys_crop_path = crops_dir / f"system_{sys_idx}.png"
                sys_rect_pt = pymupdf.Rect(
                    max(0.0, sys["x_left"] - 25.0),
                    max(0.0, sys["y_top"] - 15.0),
                    min(page_w_pt, sys["x_right"] + 15.0),
                    min(page_h_pt, sys["y_bot"] + 25.0),
                )
                pix_sys = page.get_pixmap(dpi=dpi, clip=sys_rect_pt)
                pix_sys.save(str(sys_crop_path))

                # Build measure boxes and crops
                measures_data = []
                for b_i in range(num_bars):
                    bx0 = bar_x[b_i]
                    bx1 = bar_x[b_i + 1]
                    m_num = global_measure_num
                    global_measure_num += 1

                    m_crop_path = crops_dir / f"measure_{m_num}.png"
                    m_rect_pt = pymupdf.Rect(
                        max(0.0, bx0 - 2.0),
                        max(0.0, sys["y_top"] - 10.0),
                        min(page_w_pt, bx1 + 2.0),
                        min(page_h_pt, sys["y_bot"] + 15.0),
                    )
                    pix_m = page.get_pixmap(dpi=dpi, clip=m_rect_pt)
                    pix_m.save(str(m_crop_path))

                    measures_data.append({
                        "measure_number": m_num,
                        "bar_index_in_system": b_i,
                        "crop_image_path": str(m_crop_path),
                        "bounding_box": {
                            "x": bx0,
                            "y": sys["y_top"],
                            "w": bx1 - bx0,
                            "h": sys["y_bot"] - sys["y_top"],
                        },
                    })

                m_end = global_measure_num - 1

                staves_data = []
                num_staves_in_sys = len(sys["staves"])
                is_3staff_vocal_piano = (num_staves_in_sys == 3)
                voicing_str = (score_hints.get("choral_voicing") or "").lower() if score_hints else ""
                custom_str = (score_hints.get("custom_instructions") or "").lower() if score_hints else ""
                is_male = any(k in voicing_str or k in custom_str for k in ("male", "men", "tenor", "baritone", "bass", "tb", "ttbb"))

                for st_i, st in enumerate(sys["staves"]):
                    if is_3staff_vocal_piano:
                        if st_i == 0:
                            role = "vocal_men" if is_male else "vocal"
                            bracket_type = "none"
                            clef = "treble_8vb" if is_male else st.get("clef", "treble")
                            label = "Men" if is_male else (st.get("label") or "Solo / Choir")
                        elif st_i == 1:
                            role = "piano_rh"
                            bracket_type = "brace"
                            clef = "treble"
                            label = "Piano RH"
                        else:
                            role = "piano_lh"
                            bracket_type = "brace"
                            clef = "bass"
                            label = "Piano LH"
                    else:
                        bracket_type = st.get("bracket_type", "bracket" if st_i < num_staves_in_sys - 2 else "brace")
                        role = st.get("role", "vocal")
                        clef = st.get("clef", "treble")
                        label = st.get("label")

                    staves_data.append({
                        "staff_id": f"sys{sys_idx}_st{st_i}",
                        "index": st_i,
                        "clef": clef,
                        "bracket_type": bracket_type,
                        "role": role,
                        "y_top": st["y_top"],
                        "y_bot": st["y_bot"],
                        "has_lyrics": st.get("has_lyrics", False),
                        "label": label,
                    })

                sys_payload = {
                    "system_index": sys_idx,
                    "page_num": page_num,
                    "measure_start": m_start,
                    "measure_end": m_end,
                    "crop_image_path": str(sys_crop_path),
                    "bounding_box": {
                        "x": sys["x_left"],
                        "y": sys["y_top"],
                        "w": sys["x_right"] - sys["x_left"],
                        "h": sys["y_bot"] - sys["y_top"],
                    },
                    "staves": staves_data,
                    "measures": measures_data,
                }
                page_systems_data.append(sys_payload)
                all_systems_blueprint.append(sys_payload)

            pages_data.append({
                "page_num": page_num,
                "image_path": str(page_png_path),
                "width_pt": page_w_pt,
                "height_pt": page_h_pt,
                "width_px": pix.width,
                "height_px": pix.height,
                "systems": page_systems_data,
            })

        doc.close()

        has_piano = any(
            any(st["bracket_type"] == "brace" or "piano" in (st.get("label") or "").lower() for st in s["staves"])
            or len(s["staves"]) >= 3
            for s in all_systems_blueprint
        )

        return {
            "title": title,
            "composer": composer,
            "subtitle": subtitle,
            "page_count": page_count,
            "dpi": dpi,
            "total_systems": len(all_systems_blueprint),
            "total_measures": global_measure_num - 1,
            "has_piano": has_piano,
            "pages": pages_data,
            "systems": all_systems_blueprint,
        }

    @classmethod
    def _extract_metadata(cls, doc: pymupdf.Document, pdf_path: Path) -> Tuple[str, str, str]:
        title = pdf_path.stem.replace("_", " ").title()
        composer = "Unknown Composer"
        subtitle = ""

        if len(doc) == 0:
            return title, composer, subtitle

        blacklist_terms = [
            "rehearsal", "copies", "purchased", "library", "copyright", "assigned to",
            "all rights reserved", "printed in", "oxford university press", "unauthorized",
            "photocopying", "mormon tabernacle", "music director", "dedicated to",
            "for mixed choir", "mixed choir", "satb", "keyboard", "accompaniment",
            "vocal score", "full score", "choral score", "edition", "arranger",
            "full score and set", "available on rental", "publisher"
        ]

        p0 = doc[0]
        spans = []
        for b in p0.get_text("dict").get("blocks", []):
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    txt = s.get("text", "").strip()
                    if not txt or len(txt) < 2:
                        continue
                    if any(0xE000 <= ord(ch) <= 0xF8FF for ch in txt):
                        continue
                    x0, y0, x1, y1 = s["bbox"]
                    if y0 < 220:
                        spans.append({
                            "text": txt,
                            "size": s.get("size", 10.0),
                            "x0": x0,
                            "y0": y0,
                            "x_center": (x0 + x1) / 2.0,
                        })

        if spans:
            clean_candidates = [
                sp for sp in spans
                if not any(b_term in sp["text"].lower() for b_term in blacklist_terms)
            ]

            # Title detection: prominent centered text on upper third
            title_candidates = [
                sp for sp in clean_candidates
                if 100 < sp["x_center"] < (p0.rect.width - 100) and sp["y0"] < 170
            ]
            if title_candidates:
                best_title = max(title_candidates, key=lambda x: x["size"])
                title = best_title["text"]

            # Composer detection: aligned right on upper header (above first system)
            right_spans = [
                sp for sp in clean_candidates
                if sp["x0"] > (p0.rect.width * 0.45)
                and sp["text"] != title
                and sp["y0"] < 130.0
                and not any(ch in sp["text"] for ch in [";", "!", "?"])
                and len(sp["text"].split()) <= 6
            ]
            if right_spans:
                composer = " / ".join(sp["text"] for sp in sorted(right_spans, key=lambda x: x["y0"]))

        return title, composer, subtitle

    @classmethod
    def _extract_page_systems(cls, page: pymupdf.Page, page_num: int, score_hints: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        # 1. Try vector drawing extraction first
        vector_systems = cls._extract_page_systems_vector(page, page_num, score_hints=score_hints)
        if vector_systems and any(len(s.get("staves", [])) >= 2 for s in vector_systems):
            return vector_systems

        # 2. Robust Computer Vision raster staff & system detection for scanned sheet music
        return cls._extract_page_systems_raster(page, page_num, score_hints=score_hints)

    @classmethod
    def _extract_page_systems_vector(cls, page: pymupdf.Page, page_num: int, score_hints: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        drawings = page.get_drawings()

        # Staff lines (horizontal lines > 150pt wide, < 2.5pt tall)
        horiz_lines = []
        for d in drawings:
            r = d["rect"]
            w = r.x1 - r.x0
            h = r.y1 - r.y0
            if w > 150.0 and h < 2.5:
                horiz_lines.append((round((r.y0 + r.y1) / 2.0, 2), round(r.x0, 1), round(r.x1, 1)))

        horiz_lines.sort(key=lambda x: x[0])
        unique_lines = []
        for y, x0, x1 in horiz_lines:
            if not unique_lines or abs(y - unique_lines[-1][0]) > 0.8:
                unique_lines.append([y, x0, x1])
            else:
                unique_lines[-1][1] = min(unique_lines[-1][1], x0)
                unique_lines[-1][2] = max(unique_lines[-1][2], x1)

        staves = []
        cur = []
        for line in unique_lines:
            if not cur or (line[0] - cur[-1][0]) < 11.0:
                cur.append(line)
            else:
                if len(cur) == 5:
                    staves.append({
                        "lines": [c[0] for c in cur],
                        "y_top": cur[0][0],
                        "y_bot": cur[-1][0],
                        "x_left": min(c[1] for c in cur),
                        "x_right": max(c[2] for c in cur),
                    })
                cur = [line]
        if len(cur) == 5:
            staves.append({
                "lines": [c[0] for c in cur],
                "y_top": cur[0][0],
                "y_bot": cur[-1][0],
                "x_left": min(c[1] for c in cur),
                "x_right": max(c[2] for c in cur),
            })

        if len(staves) < 2:
            return []

        # Group staves into systems
        systems = []
        idx = 0
        while idx < len(staves):
            group = [staves[idx]]
            next_idx = idx + 1
            while next_idx < len(staves):
                prev_st = group[-1]
                cand = staves[next_idx]
                gap = cand["y_top"] - prev_st["y_bot"]
                if gap < 70.0 and len(group) < 6:
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
                "x_right": group[0]["x_right"],
            })
            idx = next_idx

        cls._classify_and_segment_systems(systems, page, drawings, score_hints=score_hints)
        return systems

    @classmethod
    def _extract_page_systems_raster(cls, page: pymupdf.Page, page_num: int, score_hints: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        # Render at 150 DPI for fast and high-precision line recognition
        pix = page.get_pixmap(dpi=150)
        scale_y = page.rect.height / float(pix.height)
        scale_x = page.rect.width / float(pix.width)

        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
        gray = img.mean(axis=2) if pix.n >= 3 else img[:, :, 0]
        bw = (gray < 200).astype(np.uint8)

        # Horizontal projection profile across central 72% of page
        x0_px = int(pix.width * 0.14)
        x1_px = int(pix.width * 0.86)
        w_mid = max(1, x1_px - x0_px)
        h_proj = bw[:, x0_px:x1_px].sum(axis=1) / float(w_mid)

        thresh = max(0.20, float(h_proj.mean() + 1.2 * h_proj.std()))

        raw_peaks = []
        for y in range(1, len(h_proj) - 1):
            if h_proj[y] >= thresh and h_proj[y] >= h_proj[y - 1] and h_proj[y] >= h_proj[y + 1]:
                raw_peaks.append(y)

        # De-bounce adjacent line slices (merge peaks closer than 5px caused by ink bleed on scanned PDFs)
        peaks = []
        for p in raw_peaks:
            if not peaks or (p - peaks[-1]) > 5:
                peaks.append(p)
            else:
                if h_proj[p] > h_proj[peaks[-1]]:
                    peaks[-1] = p

        # Group 5-line staves with uniform spacing
        staves = []
        i = 0
        while i + 4 < len(peaks):
            five = peaks[i:i + 5]
            diffs = [five[k + 1] - five[k] for k in range(4)]
            avg_d = sum(diffs) / 4.0
            if 5.0 <= avg_d <= 24.0 and (max(diffs) - min(diffs)) <= 5.5:
                # Find horizontal start and end of this staff
                line_y_indices = five
                staff_row_mask = bw[line_y_indices, :].sum(axis=0) >= 2
                active_cols = np.where(staff_row_mask)[0]
                if len(active_cols) > 50:
                    x_left_pt = max(35.0, active_cols[0] * scale_x - 5.0)
                    x_right_pt = min(page.rect.width - 35.0, active_cols[-1] * scale_x + 5.0)
                else:
                    x_left_pt = 45.0
                    x_right_pt = page.rect.width - 45.0

                staves.append({
                    "lines": [p * scale_y for p in five],
                    "y_top": five[0] * scale_y,
                    "y_bot": five[4] * scale_y,
                    "x_left": x_left_pt,
                    "x_right": x_right_pt,
                })
                i += 5
            else:
                i += 1

        if not staves:
            # Fallback if page has no recognizable staves (e.g. cover page)
            return []

        # Check target staves per system from score hints (Zero Second-Guessing!)
        target_sps = None
        if score_hints and score_hints.get("staves_per_system"):
            target_sps = int(score_hints["staves_per_system"])
        elif len(staves) >= 3 and len(staves) % 3 == 0:
            target_sps = 3
        elif len(staves) >= 4 and len(staves) % 4 == 0:
            target_sps = 4

        systems = []
        if target_sps and len(staves) >= target_sps and len(staves) % target_sps == 0:
            # Deterministic System Locking: Group staves strictly into target_sps units without splitting!
            for k in range(0, len(staves), target_sps):
                group = staves[k:k + target_sps]
                systems.append({
                    "page_num": page_num,
                    "staves": group,
                    "y_top": group[0]["y_top"],
                    "y_bot": group[-1]["y_bot"],
                    "x_left": min(st["x_left"] for st in group),
                    "x_right": max(st["x_right"] for st in group),
                })
        else:
            left_x_px_max = int(pix.width * 0.22)
            left_strip = bw[:, :left_x_px_max]

            idx = 0
            while idx < len(staves):
                group = [staves[idx]]
                next_idx = idx + 1
                while next_idx < len(staves):
                    st_prev = group[-1]
                    st_curr = staves[next_idx]
                    gap_pt = st_curr["y_top"] - st_prev["y_bot"]

                    # In 3-staff layouts with vocal above piano, check left margin barline
                    y_from = int(st_prev["y_bot"] / scale_y)
                    y_to = int(st_curr["y_top"] / scale_y)
                    if y_to > y_from:
                        inter_slice = left_strip[y_from:y_to, :]
                        col_coverage = inter_slice.mean(axis=0)
                        connected = float(col_coverage.max()) >= 0.58
                    else:
                        connected = True

                    if gap_pt > 75.0 or (len(group) >= 3 and not connected) or len(group) >= 6:
                        break
                    else:
                        group.append(st_curr)
                        next_idx += 1

                systems.append({
                    "page_num": page_num,
                    "staves": group,
                    "y_top": group[0]["y_top"],
                    "y_bot": group[-1]["y_bot"],
                    "x_left": min(st["x_left"] for st in group),
                    "x_right": max(st["x_right"] for st in group),
                })
                idx = next_idx

        # Barline segmentation via raster vertical projection
        for sys in systems:
            y_t_px = max(0, int(sys["y_top"] / scale_y))
            y_b_px = min(pix.height, int(sys["y_bot"] / scale_y))
            v_slice = bw[y_t_px:y_b_px, :]
            v_proj = v_slice.sum(axis=0) / max(1.0, float(v_slice.shape[0]))
            v_thresh = max(0.22, float(v_proj.mean() + 1.8 * v_proj.std()))

            bar_pxs = []
            min_dist_px = int(35.0 / scale_x)
            for bx in range(int(pix.width * 0.08), int(pix.width * 0.92)):
                if v_proj[bx] >= v_thresh and v_proj[bx] >= v_proj[bx - 1] and v_proj[bx] >= v_proj[bx + 1]:
                    if not bar_pxs or (bx - bar_pxs[-1]) > min_dist_px:
                        bar_pxs.append(bx)

            bars_pt = [bx * scale_x for bx in bar_pxs]
            x_l = sys["x_left"]
            x_r = sys["x_right"]
            clean_bars = [x_l] + [b for b in bars_pt if (x_l + 18.0) < b < (x_r - 18.0)] + [x_r]

            if len(clean_bars) < 3:
                # Divide evenly into 4 standard measures per system
                w = x_r - x_l
                clean_bars = [x_l + (w / 4.0) * k for k in range(5)]

            sys["bar_x"] = clean_bars

        cls._classify_and_segment_systems(systems, page, None, score_hints=score_hints)
        return systems

    @classmethod
    def _classify_and_segment_systems(
        cls,
        systems: List[Dict[str, Any]],
        page: pymupdf.Page,
        drawings: Optional[List[Any]],
        score_hints: Optional[Dict[str, Any]] = None
    ):
        text_blocks = page.get_text("blocks")
        page_words = page.get_text("words")

        for sys in systems:
            y0_ref = sys["staves"][0]["y_top"]

            # If barlines were not already set by raster detection
            if "bar_x" not in sys:
                top_bars = []
                if drawings:
                    for d in drawings:
                        r = d["rect"]
                        if (r.x1 - r.x0) < 3.5 and abs(r.y0 - y0_ref) < 2.0:
                            top_bars.append(round((r.x0 + r.x1) / 2.0, 2))

                raw_bars = sorted(list(set([sys["x_left"]] + top_bars + [sys["x_right"]])))
                merged_bars = []
                for bx in raw_bars:
                    if not merged_bars or (bx - merged_bars[-1]) > 8.0:
                        merged_bars.append(bx)

                if len(merged_bars) < 2:
                    w = sys["x_right"] - sys["x_left"]
                    merged_bars = [sys["x_left"] + (w / 4.0) * i for i in range(5)]

                sys["bar_x"] = merged_bars

            # System start measure number from printed margins
            sys_m_num = None
            for b in text_blocks:
                txt = b[4].strip()
                if re.match(r"^\d+$", txt) and b[0] < 120.0:
                    if (y0_ref - 35.0) <= b[1] <= (y0_ref + 15.0):
                        sys_m_num = int(txt)
                        break
            sys["start_measure_num"] = sys_m_num

            # Classify staves using part labels and choral topology
            n_staves = len(sys["staves"])
            for st_i, st in enumerate(sys["staves"]):
                st_mid_y = (st["y_top"] + st["y_bot"]) / 2.0
                
                # Check for label words in the left margin
                nearby_words = [
                    w[4].lower() for w in page_words
                    if w[0] < 130.0 and abs(((w[1] + w[3]) / 2.0) - st_mid_y) < 25.0
                ]
                label_txt = " ".join(nearby_words)
                st["label"] = label_txt if label_txt else None

                is_bass_named = any(k in label_txt for k in ("bass", "b.", "men", "tenor & bass", "t & b"))
                is_treble_named = any(k in label_txt for k in ("soprano", "alto", "s.", "a.", "women", "s & a"))

                if n_staves >= 3:
                    if st_i >= n_staves - 2:
                        st["bracket_type"] = "brace"
                        st["role"] = "piano_rh" if st_i == n_staves - 2 else "piano_lh"
                        st["clef"] = "treble" if st_i == n_staves - 2 else "bass"
                    else:
                        st["bracket_type"] = "bracket" if n_staves > 3 else "none"
                        is_male = (score_hints and score_hints.get("choral_voicing") in ("Tenor_Bass", "TTBB", "solo_male")) or is_bass_named
                        st["role"] = "vocal_men" if is_male else "vocal"
                        if is_male:
                            st["clef"] = "treble_8vb" if not is_bass_named else "bass"
                        elif is_treble_named:
                            st["clef"] = "treble"
                        else:
                            st["clef"] = "bass" if (st_i == n_staves - 3 and n_staves >= 4) else "treble"
                elif n_staves == 2:
                    if is_treble_named and is_bass_named:
                        st["bracket_type"] = "bracket"
                        st["role"] = "vocal"
                        st["clef"] = "treble" if st_i == 0 else "bass"
                    elif is_treble_named or is_bass_named:
                        st["bracket_type"] = "bracket"
                        st["role"] = "vocal"
                        st["clef"] = "bass" if is_bass_named else "treble"
                    else:
                        # 2-staff piano accompaniment system (e.g. prelude, interlude)
                        st["bracket_type"] = "brace"
                        st["role"] = "piano_rh" if st_i == 0 else "piano_lh"
                        st["clef"] = "treble" if st_i == 0 else "bass"
                else:
                    st["bracket_type"] = "bracket"
                    st["role"] = "vocal"
                    st["clef"] = "bass" if is_bass_named else "treble"

    @classmethod
    def preflight_analysis(cls, pdf_path: Path) -> Dict[str, Any]:
        """
        Fast (~0.2s) cursory pre-flight inspection of the opening of the PDF score.
        Detects title, composer, page count, time signature, tempo BPM, and part layout / voicing
        before committing to the full heavyweight rasterization and OMR pipeline.
        """
        doc = pymupdf.open(str(pdf_path))
        page_count = len(doc)
        title, composer, subtitle = cls._extract_metadata(doc, pdf_path)

        # Inspect first 2 pages for systems, staves, text, and glyphs
        p1 = doc[0] if page_count > 0 else None
        p2 = doc[1] if page_count > 1 else None

        syss_p1 = cls._extract_page_systems(p1, 1) if p1 else []
        syss_p2 = cls._extract_page_systems(p2, 2) if p2 else []
        all_sys = list(syss_p1) + list(syss_p2)

        counts = [len(s.get("staves", [])) for s in all_sys if len(s.get("staves", [])) >= 2]
        staves_per_system = Counter(counts).most_common(1)[0][0] if counts else (len(syss_p1[0]["staves"]) if syss_p1 else 1)
        has_piano = staves_per_system >= 3 or any("piano" in (st.get("label") or "").lower() for s in all_sys for st in s.get("staves", []))

        # Text across first 2 pages
        all_text = ""
        for p in doc[:2]:
            all_text += p.get_text("text") + " "

        doc.close()

        # 1. Time Signature Detection (SMuFL Glyphs + Text Regex)
        time_sig = "4/4"
        # Check SMuFL time signature combinations
        if "\ue088\ue086" in all_text or "\ue086\ue088" in all_text:
            time_sig = "6/8"
        elif "\ue084\ue084" in all_text:
            time_sig = "4/4"
        elif "\ue083\ue084" in all_text or "\ue084\ue083" in all_text:
            time_sig = "3/4"
        elif "\ue082\ue084" in all_text or "\ue084\ue082" in all_text:
            time_sig = "2/4"
        elif "\ue082\ue082" in all_text:
            time_sig = "2/2"
        elif "\ue088\ue081\ue082" in all_text or ("\ue081\ue082" in all_text and "\ue088" in all_text):
            time_sig = "12/8"
        elif "\ue08a" in all_text:
            time_sig = "4/4"
        elif "\ue08b" in all_text:
            time_sig = "2/2"
        else:
            # Match standard fractions in text e.g. "6/8", "3/4", "4/4", "2/4", "2/2"
            frac_match = re.search(r"\b(4/4|3/4|6/8|2/4|2/2|12/8|9/8|3/8|5/4|7/8)\b", all_text)
            if frac_match:
                time_sig = frac_match.group(1)
            else:
                ratio_match = re.search(r"\b([23469]|12)\s*/\s*([248]|16)\b", all_text)
                if ratio_match:
                    time_sig = f"{ratio_match.group(1)}/{ratio_match.group(2)}"

        # 2. Starting Tempo (BPM) Detection
        tempo_bpm = 120.0
        bpm_match = re.search(r"(?:♩|q|M\.M\.|\bquarter\b|\bcrotchet\b)?\s*=\s*(\d{2,3})", all_text)
        if not bpm_match:
            bpm_match = re.search(r"=\s*(\d{2,3})", all_text)

        if bpm_match:
            val = float(bpm_match.group(1))
            if 30 <= val <= 280:
                tempo_bpm = val
        else:
            italian_tempos = {
                "largo": 56.0,
                "lento": 60.0,
                "adagio": 66.0,
                "andante": 92.0,
                "moderato": 108.0,
                "allegretto": 116.0,
                "allegro": 132.0,
                "vivace": 152.0,
                "presto": 168.0,
                "maestoso": 88.0,
            }
            lower_text = all_text.lower()
            for term, val in italian_tempos.items():
                if re.search(rf"\b{term}\b", lower_text):
                    tempo_bpm = val
                    break

        # 3. Part Layout & Voicing Topology
        lower_text = all_text.lower()
        has_soprano = bool(re.search(r"\b(soprano|s\.)\b", lower_text))
        has_alto = bool(re.search(r"\b(alto|a\.)\b", lower_text))
        has_tenor = bool(re.search(r"\b(tenor|t\.)\b", lower_text))
        has_bass = bool(re.search(r"\b(bass|b\.)\b", lower_text))

        detected_labels = []
        if has_soprano: detected_labels.append("Soprano")
        if has_alto: detected_labels.append("Alto")
        if has_tenor: detected_labels.append("Tenor")
        if has_bass: detected_labels.append("Bass")

        if staves_per_system == 6:
            choral_voicing = "SATB"
            part_layout_summary = "SATB (4 vocal staves) + Piano Accompaniment (2 staves)"
        elif staves_per_system == 5:
            if has_tenor or has_bass:
                choral_voicing = "SAB"
                part_layout_summary = "SAB (3 vocal staves) + Piano Accompaniment (2 staves)"
            else:
                choral_voicing = "SSAA"
                part_layout_summary = "SSAA (3 vocal staves) + Piano Accompaniment (2 staves)"
        elif staves_per_system == 4:
            if has_piano:
                choral_voicing = "SA_TB"
                part_layout_summary = "SA + TB (2 vocal staves) + Piano Accompaniment (2 staves)"
            else:
                choral_voicing = "SATB"
                part_layout_summary = "SATB 4-Part Choral Score (A Cappella, 4 vocal staves)"
        elif staves_per_system == 3:
            choral_voicing = "Unison"
            part_layout_summary = "Solo / Unison (1 vocal staff) + Piano Accompaniment (2 staves)"
        elif staves_per_system == 2:
            if has_soprano and has_alto and not has_tenor and not has_bass:
                choral_voicing = "SA_TB"
                part_layout_summary = "SA 2-Part Choral Score (2 vocal staves)"
            elif (has_tenor or has_bass) and not has_soprano and not has_alto:
                choral_voicing = "TTBB"
                part_layout_summary = "TB 2-Part Men's Choral Score (2 vocal staves)"
            else:
                choral_voicing = "SA_TB"
                part_layout_summary = "2-Staff Choral Score (SA + TB)"
        elif staves_per_system == 1:
            choral_voicing = "Unison"
            part_layout_summary = "Single Vocal Line (Unison / Lead Sheet)"
        else:
            choral_voicing = "SATB"
            part_layout_summary = f"{staves_per_system} staves per system (Divisi Choral + Piano Accompaniment)"

        accompaniment_type = "piano" if has_piano else "a_cappella"

        # 4. Synthesize intelligent pre-populated AI guidance prompt
        prompt_parts = []
        if has_piano:
            if staves_per_system == 3:
                prompt_parts.append("Bottom 2 staves are piano accompaniment (piano RH and piano LH); top staff is vocal line.")
            elif staves_per_system == 4:
                prompt_parts.append("Bottom 2 staves are piano accompaniment; upper 2 staves are choral vocal parts (SA on staff 1, TB on staff 2).")
            elif staves_per_system == 5:
                prompt_parts.append("Bottom 2 staves are piano accompaniment; upper 3 staves are 3-part choral harmony.")
            elif staves_per_system == 6:
                prompt_parts.append("Bottom 2 staves are piano accompaniment; upper 4 staves are SATB vocal parts.")
            else:
                prompt_parts.append("Bottom 2 staves are piano accompaniment; upper staves are choral vocal lines.")
        else:
            if staves_per_system == 4:
                prompt_parts.append("4-part SATB a cappella vocal score; all 10 vocal parts active, piano rests 100%.")
            elif staves_per_system == 2:
                prompt_parts.append("2-staff a cappella choral score; route vocal lines across canonical parts.")
            else:
                prompt_parts.append("A cappella vocal score without piano accompaniment.")

        if time_sig == "6/8":
            prompt_parts.append("Time signature is 6/8 meter (compound duple in 2 feel).")
        elif time_sig == "3/4":
            prompt_parts.append("Time signature is 3/4 triple meter.")
        elif time_sig == "2/2":
            prompt_parts.append("Time signature is 2/2 cut time.")
        elif time_sig == "2/4":
            prompt_parts.append("Time signature is 2/4 duple meter.")
        elif time_sig == "12/8":
            prompt_parts.append("Time signature is 12/8 compound quadruple meter.")
        else:
            prompt_parts.append(f"Time signature is {time_sig}.")

        if tempo_bpm and tempo_bpm != 120.0:
            prompt_parts.append(f"Starting tempo is ~{int(tempo_bpm)} BPM.")

        if detected_labels:
            prompt_parts.append(f"Vocal parts labeled: {', '.join(detected_labels)}.")

        suggested_instructions = " ".join(prompt_parts)

        # 5. Check if LearningManager recognizes this composer or layout topology
        fp = ScoreStyleFingerprint(
            staves_per_system=staves_per_system,
            inter_staff_gap_ratio=1.0,
            has_brace=has_piano,
            composer_token=re.sub(r"[^\w]", "", composer.lower()) if composer else "",
            is_scanned=len(all_text.strip()) == 0
        )
        matched_bp, conf = LearningManager.match_style(fp, composer or title)
        learned_style_match = None

        if matched_bp and conf >= 0.65:
            learned_cfg = matched_bp.verified_config
            learned_style_match = {
                "blueprint_id": matched_bp.blueprint_id,
                "name": matched_bp.name,
                "confidence": round(conf * 100, 1),
            }
            if learned_cfg.get("time_signature"):
                time_sig = learned_cfg["time_signature"]
            if learned_cfg.get("choral_voicing"):
                choral_voicing = learned_cfg["choral_voicing"]
            if learned_cfg.get("tempo_bpm"):
                tempo_bpm = float(learned_cfg["tempo_bpm"])
            if learned_cfg.get("accompaniment_type"):
                accompaniment_type = learned_cfg["accompaniment_type"]
                has_piano = accompaniment_type in ("piano", "orchestra_reduction")
            if learned_cfg.get("part_layout_summary"):
                part_layout_summary = learned_cfg["part_layout_summary"]
            if learned_cfg.get("custom_instructions"):
                suggested_instructions = learned_cfg["custom_instructions"]

        return {
            "title": title,
            "composer": composer,
            "subtitle": subtitle,
            "page_count": page_count,
            "time_signature": time_sig,
            "tempo_bpm": tempo_bpm,
            "choral_voicing": choral_voicing,
            "accompaniment_type": accompaniment_type,
            "has_piano": has_piano,
            "staves_per_system": staves_per_system,
            "part_layout_summary": part_layout_summary,
            "voice_labels_detected": detected_labels,
            "custom_instructions": suggested_instructions,
            "suggested_custom_instructions": suggested_instructions,
            "learned_style_match": learned_style_match,
        }


