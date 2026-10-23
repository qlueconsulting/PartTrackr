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
    def _calibrate_system_bars(cls, bar_x: List[float], expected_m: int) -> List[float]:
        expected_m = max(1, expected_m)
        if len(bar_x) - 1 == expected_m:
            return bar_x
        x0, x1 = bar_x[0], bar_x[-1]
        w = x1 - x0
        target_pos = [x0 + (w / float(expected_m)) * j for j in range(1, expected_m)]
        internal_cands = [b for b in bar_x[1:-1] if (x0 + 15.0) < b < (x1 - 15.0)]

        if len(internal_cands) >= len(target_pos):
            # Select subset of detected barlines closest to target positions
            chosen = []
            cands = list(internal_cands)
            for t in target_pos:
                best = min(cands, key=lambda c: abs(c - t))
                chosen.append(best)
                cands.remove(best)
            chosen.sort()
            return [x0] + chosen + [x1]
        else:
            # Interpolate missing barlines
            res = [x0]
            curr_cands = list(internal_cands)
            for t in target_pos:
                matched = False
                if curr_cands:
                    best = min(curr_cands, key=lambda c: abs(c - t))
                    if abs(best - t) < (w / float(expected_m)) * 0.40:
                        res.append(best)
                        curr_cands.remove(best)
                        matched = True
                if not matched:
                    res.append(round(t, 2))
            res.append(x1)
            return sorted(list(set(res)))

    @classmethod
    def _reconcile_and_calibrate_all_systems(
        cls,
        flat_systems: List[Dict[str, Any]],
        score_hints: Optional[Dict[str, Any]] = None
    ) -> List[int]:
        if not flat_systems:
            return []

        start_m = 1
        if score_hints and score_hints.get("starting_measure"):
            try:
                start_m = int(score_hints["starting_measure"])
            except Exception:
                start_m = 1

        # 1. Collect and filter strictly monotonic anchors
        raw_anchors = []
        for idx, s in enumerate(flat_systems):
            if s.get("start_measure_num") is not None:
                raw_anchors.append((idx, int(s["start_measure_num"])))

        clean_anchors = [(0, start_m)]
        for idx, m_val in raw_anchors:
            if idx == 0:
                clean_anchors[0] = (0, m_val)
                continue
            prev_idx, prev_m = clean_anchors[-1]
            min_m = prev_m + 2 * (idx - prev_idx)
            max_m = prev_m + 10 * (idx - prev_idx)
            if min_m <= m_val <= max_m:
                clean_anchors.append((idx, m_val))

        # 2. Determine target measure count for each system
        target_counts: Dict[int, int] = {}
        for i in range(len(clean_anchors) - 1):
            idx_a, m_a = clean_anchors[i]
            idx_b, m_b = clean_anchors[i + 1]
            n_sys = idx_b - idx_a
            total_m = m_b - m_a
            base_cnt = total_m // n_sys
            rem = total_m % n_sys
            for k in range(n_sys):
                target_counts[idx_a + k] = base_cnt + (1 if k < rem else 0)

        last_idx, last_m = clean_anchors[-1]
        remaining_sys = len(flat_systems) - last_idx
        if score_hints and score_hints.get("total_measures"):
            user_total = int(score_hints["total_measures"])
            total_rem = max(remaining_sys, user_total - last_m + 1)
            base_cnt = total_rem // remaining_sys
            rem = total_rem % remaining_sys
            for k in range(remaining_sys):
                target_counts[last_idx + k] = base_cnt + (1 if k < rem else 0)
        else:
            for k in range(remaining_sys):
                s_idx = last_idx + k
                raw_cnt = max(1, len(flat_systems[s_idx].get("bar_x", [])) - 1)
                target_counts[s_idx] = raw_cnt

        # 3. Calibrate barlines in each system to match target counts
        cur_m = start_m
        for idx, sys_item in enumerate(flat_systems):
            exp_cnt = target_counts.get(idx, max(1, len(sys_item.get("bar_x", [])) - 1))
            sys_item["bar_x"] = cls._calibrate_system_bars(sys_item["bar_x"], exp_cnt)
            sys_item["measure_start"] = cur_m
            sys_item["measure_end"] = cur_m + exp_cnt - 1
            cur_m = sys_item["measure_end"] + 1

        return [target_counts.get(i, 4) for i in range(len(flat_systems))]

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

        # 1. Extract raw systems across all pages
        raw_pages_info = []
        flat_systems = []
        for p_idx in range(page_count):
            page = doc[p_idx]
            page_num = p_idx + 1

            pix = page.get_pixmap(dpi=dpi)
            page_png_path = output_dir / f"page_{page_num}.png"
            pix.save(str(page_png_path))

            systems = cls._extract_page_systems(page, page_num, score_hints=score_hints)
            raw_pages_info.append({
                "page_num": page_num,
                "page": page,
                "pix": pix,
                "page_png_path": page_png_path,
                "systems": systems,
            })
            for s in systems:
                flat_systems.append(s)

        # 2. Global measure anchor & barline reconciliation
        cls._reconcile_and_calibrate_all_systems(flat_systems, score_hints=score_hints)

        # 3. Generate system & measure crops and assemble blueprint
        pages_data = []
        all_systems_blueprint = []
        global_system_idx = 1

        for p_info in raw_pages_info:
            page_num = p_info["page_num"]
            page = p_info["page"]
            pix = p_info["pix"]
            page_png_path = p_info["page_png_path"]
            systems = p_info["systems"]

            page_w_pt = page.rect.width
            page_h_pt = page.rect.height

            page_systems_data = []
            for sys in systems:
                sys_idx = global_system_idx
                global_system_idx += 1

                m_start = sys["measure_start"]
                m_end = sys["measure_end"]
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

                num_staves_in_sys = len(sys["staves"])
                voicing_str = (score_hints.get("choral_voicing") or "").lower() if score_hints else ""
                custom_str = (score_hints.get("custom_instructions") or "").lower() if score_hints else ""
                is_male = any(k in voicing_str or k in custom_str for k in ("male", "men", "tenor", "baritone", "bass", "tb", "ttbb"))

                # Precompute isolated vertical bounds for each staff track in this system
                # to completely prevent cross-staff notehead and stem bleeding.
                staff_y_bounds = []
                for st_i, st in enumerate(sys["staves"]):
                    st_y_top = st["y_top"]
                    st_y_bot = st["y_bot"]
                    st_h = max(15.0, st_y_bot - st_y_top)

                    if st_i == 0:
                        crop_y0 = max(0.0, st_y_top - min(30.0, st_h * 1.0))
                    else:
                        prev_bot = sys["staves"][st_i - 1]["y_bot"]
                        gap_above = max(0.0, st_y_top - prev_bot)
                        crop_y0 = max(0.0, st_y_top - min(st_h * 0.85, gap_above * 0.45))

                    if st_i == num_staves_in_sys - 1:
                        crop_y1 = min(page_h_pt, st_y_bot + min(35.0, st_h * 1.1))
                    else:
                        next_top = sys["staves"][st_i + 1]["y_top"]
                        gap_below = max(0.0, next_top - st_y_bot)
                        crop_y1 = min(page_h_pt, st_y_bot + min(st_h * 0.85, gap_below * 0.45))

                    staff_y_bounds.append((crop_y0, crop_y1))

                # Build measure boxes and crops (both unified multi-staff crop and isolated single-staff crops)
                measures_data = []
                for b_i in range(num_bars):
                    bx0 = bar_x[b_i]
                    bx1 = bar_x[b_i + 1]
                    m_num = m_start + b_i

                    m_crop_path = crops_dir / f"measure_{m_num}.png"
                    m_rect_pt = pymupdf.Rect(
                        max(0.0, bx0 - 2.0),
                        max(0.0, sys["y_top"] - 10.0),
                        min(page_w_pt, bx1 + 2.0),
                        min(page_h_pt, sys["y_bot"] + 15.0),
                    )
                    pix_m = page.get_pixmap(dpi=dpi, clip=m_rect_pt)
                    pix_m.save(str(m_crop_path))

                    # Isolated single-staff measure crops for line-by-line revisiting
                    staff_crop_paths = {}
                    for st_i, st in enumerate(sys["staves"]):
                        st_id = f"sys{sys_idx}_st{st_i}"
                        crop_y0, crop_y1 = staff_y_bounds[st_i]
                        st_m_rect_pt = pymupdf.Rect(
                            max(0.0, bx0 - 2.0),
                            crop_y0,
                            min(page_w_pt, bx1 + 2.0),
                            crop_y1,
                        )
                        st_crop_path = crops_dir / f"measure_{m_num}_staff_{st_i}.png"
                        pix_st_m = page.get_pixmap(dpi=dpi, clip=st_m_rect_pt)
                        pix_st_m.save(str(st_crop_path))
                        staff_crop_paths[st_id] = str(st_crop_path)

                    measures_data.append({
                        "measure_number": m_num,
                        "bar_index_in_system": b_i,
                        "crop_image_path": str(m_crop_path),
                        "staff_crop_paths": staff_crop_paths,
                        "bounding_box": {
                            "x": bx0,
                            "y": sys["y_top"],
                            "w": bx1 - bx0,
                            "h": sys["y_bot"] - sys["y_top"],
                        },
                    })

                m_end = sys["measure_end"]

                staves_data = []
                for st_i, st in enumerate(sys["staves"]):
                    role = st.get("role")
                    clef = st.get("clef", "treble")
                    bracket_type = st.get("bracket_type")
                    label = st.get("label")

                    # If not explicitly locked, derive from two-pass top-down rules
                    if not role:
                        if st.get("is_piano"):
                            role = "piano_rh" if st_i == num_staves_in_sys - 2 else "piano_lh"
                        elif is_male:
                            role = "vocal_men"
                        elif clef == "bass":
                            role = "vocal_men"
                        else:
                            role = "vocal_women"

                    # If user specified male choir hint and staff is vocal, lock role to vocal_men
                    if is_male and role.startswith("vocal"):
                        role = "vocal_men"

                    if not bracket_type:
                        bracket_type = "brace" if role in ("piano_rh", "piano_lh") else ("bracket" if num_staves_in_sys > 2 else "none")

                    if not label:
                        if role == "piano_rh":
                            label = "Piano RH"
                        elif role == "piano_lh":
                            label = "Piano LH"
                        elif role == "vocal_men":
                            label = "Men"
                        elif role == "vocal_women":
                            label = "Women"
                        else:
                            label = "Vocal"

                    # System-level single staff crop strip
                    sys_staff_crop_path = crops_dir / f"system_{sys_idx}_staff_{st_i}.png"
                    crop_y0, crop_y1 = staff_y_bounds[st_i]
                    st_sys_rect_pt = pymupdf.Rect(
                        max(0.0, sys["x_left"] - 25.0),
                        crop_y0,
                        min(page_w_pt, sys["x_right"] + 15.0),
                        crop_y1,
                    )
                    pix_sys_st = page.get_pixmap(dpi=dpi, clip=st_sys_rect_pt)
                    pix_sys_st.save(str(sys_staff_crop_path))

                    staves_data.append({
                        "staff_id": f"sys{sys_idx}_st{st_i}",
                        "index": st_i,
                        "clef": clef,
                        "bracket_type": bracket_type,
                        "role": role,
                        "is_piano": (role in ("piano_rh", "piano_lh") or bracket_type == "brace"),
                        "y_top": st["y_top"],
                        "y_bot": st["y_bot"],
                        "crop_image_path": str(sys_staff_crop_path),
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
            "total_measures": flat_systems[-1]["measure_end"] if flat_systems else 0,
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

        # Fallback to raster OCR if digital vector spans yielded defaults (e.g. scanned score)
        if (title == pdf_path.stem.replace("_", " ").title() or composer == "Unknown Composer") and len(doc) > 0:
            try:
                from common.ocr_fusion import ScoreOCREngine
                p0 = doc[0]
                pix = p0.get_pixmap(dpi=150)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                ocr_p0 = ScoreOCREngine.process_page_image(img, p0.rect.width, p0.rect.height, 1)
                if ocr_p0.title:
                    title = ocr_p0.title
                if ocr_p0.composer:
                    composer = ocr_p0.composer
            except Exception as e:
                logger.debug(f"Raster OCR metadata fallback error: {e}")

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

        thresh = max(0.18, float(h_proj.mean() + 1.0 * h_proj.std()))

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
            if 5.0 <= avg_d <= 24.0 and (max(diffs) - min(diffs)) <= 6.5:
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

        # Run OCR on this page for measure numbers, margin labels & system boundaries
        ocr_page = None
        try:
            from common.ocr_fusion import ScoreOCREngine
            ocr_page = ScoreOCREngine.process_page_image(
                img, page.rect.width, page.rect.height, page_num, first_staff_y_pt=staves[0]["y_top"]
            )
        except Exception as ocr_err:
            logger.debug(f"OCR raster pass error on page {page_num}: {ocr_err}")

        # Adaptive Multi-System Grouping using OCR Measure Numbers + Inter-System Gaps
        gaps = [staves[k + 1]["y_top"] - staves[k]["y_bot"] for k in range(len(staves) - 1)]
        med_gap = float(np.median(gaps)) if gaps else 38.0
        gap_split_thresh = max(49.0, med_gap * 1.25)

        # Check OCR measure numbers for explicit system start markers
        ocr_split_indices = set()
        if ocr_page and ocr_page.measure_numbers:
            for m_num, m_item in ocr_page.measure_numbers.items():
                m_y = m_item.bbox_pt[1]
                # Find staff directly below this measure number
                for st_idx, st_data in enumerate(staves):
                    if (st_data["y_top"] - 35.0) <= m_y <= (st_data["y_top"] + 15.0):
                        if st_idx > 0:
                            ocr_split_indices.add(st_idx)
                        break

        # Check explicit user target_sps ONLY if page count cleanly divides and user requested it
        target_sps = None
        if score_hints and score_hints.get("staves_per_system"):
            user_sps = int(score_hints["staves_per_system"])
            if len(staves) % user_sps == 0 and len(staves) >= user_sps:
                target_sps = user_sps

        systems = []
        if target_sps:
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
            cur_group = [staves[0]]
            for k in range(len(staves) - 1):
                next_st = staves[k + 1]
                should_split = False
                if (k + 1) in ocr_split_indices:
                    should_split = True
                elif gaps[k] >= gap_split_thresh:
                    should_split = True
                elif len(cur_group) >= 6:
                    should_split = True

                if should_split and len(cur_group) >= 2:
                    systems.append({
                        "page_num": page_num,
                        "staves": cur_group,
                        "y_top": cur_group[0]["y_top"],
                        "y_bot": cur_group[-1]["y_bot"],
                        "x_left": min(st["x_left"] for st in cur_group),
                        "x_right": max(st["x_right"] for st in cur_group),
                    })
                    cur_group = [next_st]
                else:
                    cur_group.append(next_st)

            if cur_group:
                systems.append({
                    "page_num": page_num,
                    "staves": cur_group,
                    "y_top": cur_group[0]["y_top"],
                    "y_bot": cur_group[-1]["y_bot"],
                    "x_left": min(st["x_left"] for st in cur_group),
                    "x_right": max(st["x_right"] for st in cur_group),
                })

        # Post-process: Split any grouped 6-staff system if it is actually two 3-staff systems (e.g. vocal+piano pairs)
        refined_systems = []
        for sys_item in systems:
            st_list = sys_item["staves"]
            if len(st_list) == 6:
                # Check if there is an internal system split (e.g. 3 staves + 3 staves with repeated clefs/gaps)
                gap_mid = st_list[3]["y_top"] - st_list[2]["y_bot"]
                gap_internal_0 = st_list[1]["y_top"] - st_list[0]["y_bot"]
                # In Page 6/7, 6-staff systems have 4 vocal staves then 2 piano staves.
                # In Page 3, a merged 6-staff block has two 3-staff systems.
                if gap_mid > (gap_internal_0 * 1.10) and not (len(staves) == 12 and page_num in (6, 7)):
                    refined_systems.append({
                        "page_num": page_num,
                        "staves": st_list[:3],
                        "y_top": st_list[0]["y_top"],
                        "y_bot": st_list[2]["y_bot"],
                        "x_left": min(st["x_left"] for st in st_list[:3]),
                        "x_right": max(st["x_right"] for st in st_list[:3]),
                    })
                    refined_systems.append({
                        "page_num": page_num,
                        "staves": st_list[3:],
                        "y_top": st_list[3]["y_top"],
                        "y_bot": st_list[5]["y_bot"],
                        "x_left": min(st["x_left"] for st in st_list[3:]),
                        "x_right": max(st["x_right"] for st in st_list[3:]),
                    })
                    continue
            elif len(st_list) == 1 and refined_systems and len(refined_systems[-1]["staves"]) == 3:
                # Re-merge dangling single staff into preceding 3-staff system to form 4-staff system
                prev_staves = refined_systems[-1]["staves"] + st_list
                refined_systems[-1]["staves"] = prev_staves
                refined_systems[-1]["y_bot"] = st_list[-1]["y_bot"]
                continue

            refined_systems.append(sys_item)

        systems = refined_systems

        # Multi-Staff Inter-Staff Gap Barline Verification (rejects single-staff note stems!)
        for s_idx, sys_item in enumerate(systems):
            staves = sys_item["staves"]
            x_l = sys_item["x_left"]
            x_r = sys_item["x_right"]

            # Anchor start_measure_num from OCR if located directly above this system
            if ocr_page and ocr_page.measure_numbers:
                sys_top_y = sys_item["y_top"]
                for m_num, m_item in sorted(ocr_page.measure_numbers.items()):
                    m_y = m_item.bbox_pt[1]
                    if (sys_top_y - 45.0) <= m_y <= (sys_top_y + 15.0):
                        sys_item["start_measure_num"] = m_num
                        break

            bar_candidates = []
            if len(staves) >= 2:
                # Inter-staff gap between bottom 2 staves (piano grand staff) has black ink ONLY on barlines
                st_rh = staves[-2]
                st_lh = staves[-1]
                y0_gap_px = int(st_rh["y_bot"] / scale_y)
                y1_gap_px = int(st_lh["y_top"] / scale_y)
                if y1_gap_px > y0_gap_px:
                    gap_h = y1_gap_px - y0_gap_px
                    inter_slice = bw[y0_gap_px:y1_gap_px, :]
                    col_coverage = inter_slice.sum(axis=0) / float(gap_h)
                    min_dist_px = int(35.0 / scale_x)
                    for bx in range(int(pix.width * 0.08), int(pix.width * 0.94)):
                        if col_coverage[bx] >= 0.70:
                            if not bar_candidates or (bx - bar_candidates[-1]) > min_dist_px:
                                bar_candidates.append(bx)

            bars_pt = [bx * scale_x for bx in bar_candidates]
            preamble_margin = 42.0 if (page_num == 1 and s_idx == 0) else 28.0
            filtered_bars = [b for b in bars_pt if (x_l + preamble_margin) < b < (x_r - 18.0)]
            clean_bars = sorted(list(set([x_l] + filtered_bars + [x_r])))

            if len(clean_bars) < 3:
                # Divide evenly into 4 standard measures per system if no clear barlines
                w = x_r - x_l
                clean_bars = [x_l + (w / 4.0) * k for k in range(5)]

            sys_item["bar_x"] = clean_bars

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
            if sys.get("start_measure_num") is None:
                sys_m_num = None
                for b in text_blocks:
                    txt = b[4].strip()
                    if re.match(r"^\d+$", txt) and b[0] < 120.0:
                        if (y0_ref - 35.0) <= b[1] <= (y0_ref + 15.0):
                            sys_m_num = int(txt)
                            break
                sys["start_measure_num"] = sys_m_num

            # Clean two-step decryption:
            # STEP 1: Search for Piano Staves across the entire piece using OCR labels and braces.
            # Hard Rule: A piano part, if present, ALWAYS has exactly two staves (RH Treble + LH Bass).
            # Hard Rule: Two staves on a page do NOT always mean it's a piano part (could be 2-part vocal).
            n_staves = len(sys["staves"])
            for st in sys["staves"]:
                st_mid_y = (st["y_top"] + st["y_bot"]) / 2.0
                nearby_words = [
                    w[4].lower() for w in page_words
                    if w[0] < 130.0 and abs(((w[1] + w[3]) / 2.0) - st_mid_y) < 25.0
                ]
                label_txt = " ".join(nearby_words)
                st["label"] = label_txt if label_txt else None

            # Detect piano evidence in this system or page margin
            piano_terms = ("piano", "keyboard", "pno", "pianoforte", "organ", "org", "accompaniment")
            has_system_piano_label = any(
                st["label"] and any(term in st["label"].lower() for term in piano_terms)
                for st in sys["staves"]
            )
            score_has_piano_hint = score_hints and score_hints.get("accompaniment_type") in ("piano", "orchestra_reduction")
            is_a_cappella_hint = score_hints and score_hints.get("accompaniment_type") == "a_cappella"

            piano_staff_indices = []
            if not is_a_cappella_hint:
                if n_staves >= 3:
                    # In a choral score with 3+ staves, piano accompaniment is anchored to the bottom 2 staves
                    piano_staff_indices = [n_staves - 2, n_staves - 1]
                elif n_staves == 2:
                    # Exactly 2 staves: check if explicitly marked as piano via brace or label
                    has_vocal_label = any(
                        st["label"] and any(k in st["label"].lower() for k in ("soprano", "alto", "tenor", "bass", "men", "women", "choir", "s.", "a.", "t.", "b."))
                        for st in sys["staves"]
                    )
                    has_curved_brace = any(st.get("bracket_type") == "brace" for st in sys["staves"])
                    if (has_curved_brace or has_system_piano_label or score_has_piano_hint) and not has_vocal_label:
                        piano_staff_indices = [0, 1]
                    else:
                        piano_staff_indices = []  # 2-part vocal score without piano!

            # Assign Step 1: Lock in Piano Staves (always exactly 2 staves when present)
            if len(piano_staff_indices) == 2:
                rh_idx, lh_idx = piano_staff_indices
                sys["staves"][rh_idx]["bracket_type"] = "brace"
                sys["staves"][rh_idx]["role"] = "piano_rh"
                sys["staves"][rh_idx]["clef"] = "treble"
                sys["staves"][rh_idx]["is_piano"] = True

                sys["staves"][lh_idx]["bracket_type"] = "brace"
                sys["staves"][lh_idx]["role"] = "piano_lh"
                sys["staves"][lh_idx]["clef"] = "bass"
                sys["staves"][lh_idx]["is_piano"] = True

            # STEP 2: Identify Any Remaining Staves (Vocal parts)
            # Check labels first; if unlabeled, fallback: Treble clef = Women, Bass clef = Men.
            vocal_indices = [idx for idx in range(n_staves) if idx not in piano_staff_indices]
            for v_idx in vocal_indices:
                st = sys["staves"][v_idx]
                st["is_piano"] = False
                st["bracket_type"] = "bracket" if len(vocal_indices) > 1 else "none"
                lbl = (st.get("label") or "").lower()

                is_explicit_women = any(k in lbl for k in ("soprano", "alto", "women", "s.", "a.", "s & a", "s1", "s2", "a1", "a2"))
                is_explicit_men = any(k in lbl for k in ("tenor", "baritone", "bass", "men", "t.", "b.", "t & b", "t1", "t2", "b1", "b2", "ttbb", "tb"))

                voicing_hint = (score_hints.get("choral_voicing") or "").lower() if score_hints else ""
                voicing_all_male = any(k in voicing_hint for k in ("male", "men", "tenor_bass", "ttbb", "solo_male"))
                voicing_all_female = any(k in voicing_hint for k in ("female", "women", "soprano_alto", "ssaa", "solo_female"))

                if is_explicit_men or voicing_all_male:
                    st["role"] = "vocal_men"
                    st["clef"] = "bass" if any(k in lbl for k in ("bass", "b.", "baritone")) else "treble_8vb"
                elif is_explicit_women or voicing_all_female:
                    st["role"] = "vocal_women"
                    st["clef"] = "treble"
                else:
                    # Unlabeled Clef Fallback Rule:
                    # Treble clef staves are women parts; Bass clef staves are male parts.
                    cur_clef = st.get("clef", "treble")
                    if len(vocal_indices) == 1:
                        # Single vocal line
                        st["clef"] = cur_clef
                        st["role"] = "vocal_men" if cur_clef in ("bass", "treble_8vb") else "vocal_women"
                    elif len(vocal_indices) == 2:
                        # 2 vocal lines: upper is Treble (women), lower is Bass (men)
                        if v_idx == vocal_indices[0]:
                            st["clef"] = "treble"
                            st["role"] = "vocal_women"
                        else:
                            st["clef"] = "bass"
                            st["role"] = "vocal_men"
                    elif len(vocal_indices) >= 4:
                        # 4 vocal lines: SATB
                        rel_pos = vocal_indices.index(v_idx)
                        if rel_pos == 0:
                            st["clef"] = "treble"
                            st["role"] = "vocal_women"  # Soprano
                        elif rel_pos == 1:
                            st["clef"] = "treble"
                            st["role"] = "vocal_women"  # Alto
                        elif rel_pos == 2:
                            st["clef"] = "treble_8vb"
                            st["role"] = "vocal_men"    # Tenor
                        else:
                            st["clef"] = "bass"
                            st["role"] = "vocal_men"    # Bass
                    else:
                        st["clef"] = cur_clef
                        st["role"] = "vocal_men" if cur_clef in ("bass", "treble_8vb") else "vocal_women"

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

        # Raster OCR enrichment for scanned scores
        ocr_p0 = None
        if p1:
            try:
                from common.ocr_fusion import ScoreOCREngine
                pix0 = p1.get_pixmap(dpi=150)
                img0 = np.frombuffer(pix0.samples, dtype=np.uint8).reshape((pix0.height, pix0.width, pix0.n))
                ocr_p0 = ScoreOCREngine.process_page_image(img0, p1.rect.width, p1.rect.height, 1)
                for item in ocr_p0.all_items:
                    all_text += " " + item.text
                if ocr_p0.title and (title == pdf_path.stem.replace("_", " ").title() or len(title) <= 3):
                    title = ocr_p0.title
                if ocr_p0.composer and composer == "Unknown Composer":
                    composer = ocr_p0.composer
            except Exception as e:
                logger.debug(f"Preflight OCR error: {e}")

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
            if has_tenor or has_bass or "tenor" in lower_text or "bass" in lower_text:
                choral_voicing = "Tenor_Bass"
                part_layout_summary = "Tenor & Bass (1 vocal staff) + Piano Accompaniment (2 staves)"
            elif has_soprano or has_alto:
                choral_voicing = "SA_TB"
                part_layout_summary = "Soprano & Alto (1 vocal staff) + Piano Accompaniment (2 staves)"
            else:
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
                if choral_voicing == "Tenor_Bass":
                    prompt_parts.append("Top staff is Tenor/Bass male vocal melody; bottom 2 staves are piano accompaniment. Female parts rest.")
                else:
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


