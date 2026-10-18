import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
import pymupdf
import numpy as np

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
        dpi: int = 300
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
            systems = cls._extract_page_systems(page, page_num)

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
                for st_i, st in enumerate(sys["staves"]):
                    staves_data.append({
                        "staff_id": f"sys{sys_idx}_st{st_i}",
                        "index": st_i,
                        "clef": st.get("clef", "treble"),
                        "bracket_type": st.get("bracket_type", "bracket" if st_i < len(sys["staves"]) - 2 else "brace"),
                        "role": st.get("role", "vocal"),
                        "y_top": st["y_top"],
                        "y_bot": st["y_bot"],
                        "has_lyrics": st.get("has_lyrics", False),
                        "label": st.get("label"),
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
    def _extract_page_systems(cls, page: pymupdf.Page, page_num: int) -> List[Dict[str, Any]]:
        # 1. Try vector drawing extraction first
        vector_systems = cls._extract_page_systems_vector(page, page_num)
        if vector_systems and any(len(s.get("staves", [])) >= 2 for s in vector_systems):
            return vector_systems

        # 2. Robust Computer Vision raster staff & system detection for scanned sheet music
        return cls._extract_page_systems_raster(page, page_num)

    @classmethod
    def _extract_page_systems_vector(cls, page: pymupdf.Page, page_num: int) -> List[Dict[str, Any]]:
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
                if gap < 70.0:
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

        cls._classify_and_segment_systems(systems, page, drawings)
        return systems

    @classmethod
    def _extract_page_systems_raster(cls, page: pymupdf.Page, page_num: int) -> List[Dict[str, Any]]:
        # Render at 150 DPI for fast and high-precision line recognition
        pix = page.get_pixmap(dpi=150)
        scale_y = page.rect.height / float(pix.height)
        scale_x = page.rect.width / float(pix.width)

        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
        gray = img.mean(axis=2) if pix.n >= 3 else img[:, :, 0]
        bw = (gray < 200).astype(np.uint8)

        # Horizontal projection profile across central 76% of page
        x0_px = int(pix.width * 0.12)
        x1_px = int(pix.width * 0.88)
        w_mid = max(1, x1_px - x0_px)
        h_proj = bw[:, x0_px:x1_px].sum(axis=1) / float(w_mid)

        thresh = max(0.28, float(h_proj.mean() + 1.8 * h_proj.std()))

        # Detect line peaks
        peaks = []
        for y in range(1, len(h_proj) - 1):
            if h_proj[y] >= thresh and h_proj[y] >= h_proj[y - 1] and h_proj[y] >= h_proj[y + 1]:
                if not peaks or (y - peaks[-1]) > 3:
                    peaks.append(y)

        # Group 5-line staves with uniform spacing
        staves = []
        i = 0
        while i + 4 < len(peaks):
            five = peaks[i:i + 5]
            diffs = [five[k + 1] - five[k] for k in range(4)]
            avg_d = sum(diffs) / 4.0
            if 4.5 <= avg_d <= 25.0 and (max(diffs) - min(diffs)) <= 4.5:
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

        # Group staves into systems by vertical spacing (< 75pt within system)
        systems = []
        idx = 0
        while idx < len(staves):
            group = [staves[idx]]
            next_idx = idx + 1
            while next_idx < len(staves):
                gap = staves[next_idx]["y_top"] - group[-1]["y_bot"]
                if gap < 75.0:
                    group.append(staves[next_idx])
                    next_idx += 1
                else:
                    break
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

        cls._classify_and_segment_systems(systems, page, None)
        return systems

    @classmethod
    def _classify_and_segment_systems(
        cls,
        systems: List[Dict[str, Any]],
        page: pymupdf.Page,
        drawings: Optional[List[Any]]
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
                        st["bracket_type"] = "bracket"
                        st["role"] = "vocal"
                        if is_bass_named:
                            st["clef"] = "bass"
                        elif is_treble_named:
                            st["clef"] = "treble"
                        else:
                            st["clef"] = "bass" if (st_i == n_staves - 3 and n_staves >= 4) else "treble"
                elif n_staves == 2:
                    st["bracket_type"] = "bracket"
                    st["role"] = "vocal"
                    st["clef"] = "bass" if (is_bass_named or st_i == 1) else "treble"
                else:
                    st["bracket_type"] = "bracket"
                    st["role"] = "vocal"
                    st["clef"] = "bass" if is_bass_named else "treble"
