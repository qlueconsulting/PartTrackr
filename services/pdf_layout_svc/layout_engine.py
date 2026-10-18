import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
import pymupdf

logger = logging.getLogger("pdf_layout_svc")


class PDFLayoutEngine:
    """
    Renders PDF pages to 300 DPI high-resolution PNGs, detects systems,
    staves, barlines, brackets, measure boxes, and produces cropped measure images.
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

            scale = dpi / 72.0  # PDF points are 72 DPI
            page_w_pt = page.rect.width
            page_h_pt = page.rect.height

            # 2. Extract page systems, staff lines, and barlines in point coordinates
            systems = cls._extract_page_systems(page, page_num)

            page_systems_data = []
            for sys in systems:
                sys_idx = global_system_idx
                global_system_idx += 1

                # Starting measure override if printed in score
                if sys.get("start_measure_num") is not None:
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

        p0 = doc[0]
        spans = []
        for b in p0.get_text("dict").get("blocks", []):
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    txt = s.get("text", "").strip()
                    if not txt:
                        continue
                    if any(0xE000 <= ord(ch) <= 0xF8FF for ch in txt):
                        continue
                    x0, y0, x1, y1 = s["bbox"]
                    if y0 < 150:
                        spans.append({
                            "text": txt,
                            "size": s.get("size", 10.0),
                            "x0": x0,
                            "y0": y0,
                            "x_center": (x0 + x1) / 2.0,
                        })

        if spans:
            centered = [
                sp for sp in spans
                if 120 < sp["x_center"] < 500 and sp["text"].lower() not in ("choir", "piano", "vocal score", "satb")
            ]
            if centered:
                best_title = max(centered, key=lambda x: x["size"])
                title = best_title["text"]
                subs = [sp["text"] for sp in centered if sp is not best_title and sp["y0"] > best_title["y0"]]
                if subs:
                    subtitle = " — ".join(subs)

            right_spans = [sp for sp in spans if sp["x0"] > 350 and sp["text"] != title]
            if right_spans:
                composer = " / ".join(sp["text"] for sp in sorted(right_spans, key=lambda x: x["y0"]))

        return title, composer, subtitle

    @classmethod
    def _extract_page_systems(cls, page: pymupdf.Page, page_num: int) -> List[Dict[str, Any]]:
        drawings = page.get_drawings()

        # 1. Staff lines (horizontal lines > 150pt wide, < 2.5pt tall)
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

        # 2. Group into 5-line staves
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

        if not staves:
            # Fallback if vector lines weren't parsed as drawings
            return [{
                "page_num": page_num,
                "staves": [{
                    "lines": [100.0, 110.0, 120.0, 130.0, 140.0],
                    "y_top": 100.0,
                    "y_bot": 140.0,
                    "x_left": 50.0,
                    "x_right": page.rect.width - 50.0,
                    "clef": "treble",
                    "bracket_type": "bracket",
                    "role": "vocal",
                }],
                "y_top": 90.0,
                "y_bot": 150.0,
                "x_left": 50.0,
                "x_right": page.rect.width - 50.0,
                "bar_x": [50.0, page.rect.width - 50.0],
            }]

        # 3. Group staves into systems by vertical spacing and vertical connector bars
        systems = []
        idx = 0
        while idx < len(staves):
            s_top = staves[idx]
            group = [s_top]
            next_idx = idx + 1
            while next_idx < len(staves):
                prev_st = group[-1]
                cand = staves[next_idx]
                gap = cand["y_top"] - prev_st["y_bot"]
                # Staves within the same system are usually spaced < 65pt apart
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

        # 4. Text and barlines
        text_blocks = page.get_text("blocks")
        for sys in systems:
            y0_ref = sys["staves"][0]["y_top"]
            y1_ref = sys["staves"][0]["y_bot"]

            # Barlines
            top_bars = []
            for d in drawings:
                r = d["rect"]
                if (r.x1 - r.x0) < 3.5 and abs(r.y0 - y0_ref) < 1.5 and abs(r.y1 - y1_ref) < 1.5:
                    top_bars.append(round((r.x0 + r.x1) / 2.0, 2))

            raw_bars = sorted(list(set([sys["x_left"]] + top_bars + [sys["x_right"]])))
            merged_bars = []
            for bx in raw_bars:
                if not merged_bars or (bx - merged_bars[-1]) > 8.0:
                    merged_bars.append(bx)

            if len(merged_bars) < 2:
                # Default 4 measure divisions across the width if no barlines detected
                w = sys["x_right"] - sys["x_left"]
                merged_bars = [sys["x_left"] + (w / 4.0) * i for i in range(5)]

            sys["bar_x"] = merged_bars

            # System start measure number
            sys_m_num = None
            for b in text_blocks:
                txt = b[4].strip()
                if re.match(r"^\d+$", txt) and b[0] < 110.0:
                    if (y0_ref - 35.0) <= b[1] <= (y0_ref + 10.0):
                        sys_m_num = int(txt)
                        break
            sys["start_measure_num"] = sys_m_num

            # Classify staves (Choir bracket vs Piano brace)
            n_staves = len(sys["staves"])
            for st_i, st in enumerate(sys["staves"]):
                if n_staves >= 3:
                    if st_i >= n_staves - 2:
                        st["bracket_type"] = "brace"
                        st["role"] = "piano_rh" if st_i == n_staves - 2 else "piano_lh"
                        st["clef"] = "treble" if st_i == n_staves - 2 else "bass"
                    else:
                        st["bracket_type"] = "bracket"
                        st["role"] = "vocal"
                        st["clef"] = "bass" if st_i == n_staves - 3 and n_staves >= 4 else "treble"
                elif n_staves == 2:
                    st["bracket_type"] = "bracket"
                    st["role"] = "vocal"
                    st["clef"] = "treble" if st_i == 0 else "bass"
                else:
                    st["bracket_type"] = "bracket"
                    st["role"] = "vocal"
                    st["clef"] = "treble"

        return systems
