import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
import numpy as np

logger = logging.getLogger("common.ocr_fusion")

# Try importing RapidOCR
try:
    from rapidocr_onnxruntime import RapidOCR
    _RAPID_OCR_AVAILABLE = True
    _OCR_ENGINE = RapidOCR()
except Exception as e:
    logger.warning(f"RapidOCR not available: {e}")
    _RAPID_OCR_AVAILABLE = False
    _OCR_ENGINE = None


@dataclass
class ScoreOCRItem:
    text: str
    confidence: float
    # Point coordinates on PDF page [x0, y0, x1, y1]
    bbox_pt: Tuple[float, float, float, float]
    # Pixel coordinates on image [px0, py0, px1, py1]
    bbox_px: Tuple[int, int, int, int]
    zone: str = "unknown"  # header, left_margin, lyrics, directive, measure_number


@dataclass
class ScoreOCRPageResult:
    page_num: int
    title: Optional[str] = None
    composer: Optional[str] = None
    tempo_text: Optional[str] = None
    margin_labels: List[ScoreOCRItem] = field(default_factory=list)
    measure_numbers: Dict[int, ScoreOCRItem] = field(default_factory=dict)
    lyrics: List[ScoreOCRItem] = field(default_factory=list)
    directives: List[ScoreOCRItem] = field(default_factory=list)
    all_items: List[ScoreOCRItem] = field(default_factory=list)


class ScoreOCREngine:
    """
    Dual-stream OCR Engine for Choral Scores:
    1. Extracts printed text (lyrics, labels, tempo expressions, dynamics, measure numbers).
    2. Classifies words into semantic zones.
    3. Produces a Text Exclusion Mask to prevent text from being misidentified as musical notes.
    """

    BLACKLIST_PATTERNS = [
        r"copies\s+for\s+rehearsal",
        r"originals\s+purchased",
        r"for\s+rehearsal\s+purposes",
        r"oxford\s+university\s+press",
        r"unauthorized\s+photocopying",
        r"all\s+rights\s+reserved",
        r"printed\s+in",
        r"assigned\s+to",
        r"full\s+score\s+and\s+set",
        r"available\s+on\s+rental",
    ]

    DYNAMIC_TERMS = {
        "ppp", "pp", "p", "mp", "mf", "f", "ff", "fff", "sfz", "fp",
        "unis.mp", "unis.mf", "unis.f", "unis.p", "unis."
    }

    TEMPO_TERMS = [
        "poco rit.", "rit.", "ritard.", "a tempo", "poco meno mosso", "meno mosso",
        "piu mosso", "allegro", "andante", "adagio", "largo", "moderato", "maestoso"
    ]

    VOICE_TERMS = [
        "soprano", "alto", "tenor", "bass", "men", "women", "keyboard",
        "s.", "a.", "t.", "b.", "organ", "piano"
    ]

    @classmethod
    def is_blacklisted(cls, text: str) -> bool:
        t_low = text.lower()
        return any(re.search(pat, t_low) for pat in cls.BLACKLIST_PATTERNS)

    @classmethod
    def process_page_image(
        cls,
        image_np: np.ndarray,
        page_w_pt: float,
        page_h_pt: float,
        page_num: int = 1,
        first_staff_y_pt: Optional[float] = None,
        staves_info: Optional[List[Dict[str, Any]]] = None
    ) -> ScoreOCRPageResult:
        res = ScoreOCRPageResult(page_num=page_num)
        if not _RAPID_OCR_AVAILABLE or _OCR_ENGINE is None:
            return res

        h_px, w_px = image_np.shape[:2]
        scale_x = page_w_pt / float(w_px)
        scale_y = page_h_pt / float(h_px)

        try:
            raw_ocr, _ = _OCR_ENGINE(image_np)
        except Exception as e:
            logger.warning(f"OCR execution failed on page {page_num}: {e}")
            return res

        if not raw_ocr:
            return res

        y_header_cutoff = first_staff_y_pt if first_staff_y_pt else (page_h_pt * 0.28)

        for item in raw_ocr:
            coords, text, conf = item
            text_str = text.strip()
            if not text_str or cls.is_blacklisted(text_str):
                continue

            xs = [pt[0] for pt in coords]
            ys = [pt[1] for pt in coords]
            px0, py0, px1, py1 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
            pt_x0, pt_y0 = px0 * scale_x, py0 * scale_y
            pt_x1, pt_y1 = px1 * scale_x, py1 * scale_y
            bbox_pt = (pt_x0, pt_y0, pt_x1, pt_y1)
            bbox_px = (px0, py0, px1, py1)

            ocr_item = ScoreOCRItem(
                text=text_str,
                confidence=float(conf),
                bbox_pt=bbox_pt,
                bbox_px=bbox_px
            )

            t_lower = text_str.lower()
            is_tempo = ("with " in t_lower or "tempo" in t_lower or any(tt in t_lower for tt in cls.TEMPO_TERMS)) and len(text_str) >= 4

            # 1. Measure Numbers in Left Margin (1-3 digits, below top-edge folio page number)
            if re.match(r"^\d{1,3}$", text_str) and pt_x0 < (page_w_pt * 0.22) and pt_y1 > 28.0:
                ocr_item.zone = "measure_number"
                m_val = int(text_str)
                res.measure_numbers[m_val] = ocr_item

            # 2. Header Zone (above top system)
            elif pt_y1 < y_header_cutoff or (is_tempo and pt_y0 < (y_header_cutoff + 35.0)):
                ocr_item.zone = "header"
                if is_tempo:
                    if not res.tempo_text:
                        res.tempo_text = text_str
                    else:
                        res.tempo_text += " " + text_str
                elif pt_x0 > (page_w_pt * 0.45):
                    # Composer / Arranger aligned right
                    if any(w in t_lower for w in ["arr", "mack", "wilberg", "carol", "bach", "traditional"]):
                        if not res.composer:
                            res.composer = text_str
                        else:
                            res.composer += " / " + text_str
                elif (page_w_pt * 0.15) < (pt_x0 + pt_x1) / 2.0 < (page_w_pt * 0.85):
                    # Centered title candidates - choose largest font height
                    box_h = pt_y1 - pt_y0
                    if not any(w in t_lower for w in ["for", "mixed", "choir", "satb", "mormon", "director"]):
                        if not res.title or box_h > getattr(res, "_best_title_h", 0.0):
                            res.title = text_str
                            res._best_title_h = box_h

            # 3. Left Margin Zone (part labels)
            elif pt_x0 < (page_w_pt * 0.22):
                ocr_item.zone = "left_margin"
                res.margin_labels.append(ocr_item)

            # 3. Directives (Dynamics, tempo, expression)
            elif any(d == text_str.lower() or text_str.lower().startswith(d) for d in cls.DYNAMIC_TERMS) or any(tt in text_str.lower() for tt in cls.TEMPO_TERMS):
                ocr_item.zone = "directive"
                res.directives.append(ocr_item)

            # 4. Lyrics vs Note Interstitial
            else:
                ocr_item.zone = "lyrics"
                res.lyrics.append(ocr_item)

            res.all_items.append(ocr_item)

        return res

    @classmethod
    def create_text_exclusion_mask(
        cls,
        image_shape: Tuple[int, int],
        ocr_items: List[ScoreOCRItem],
        staff_y_ranges_px: Optional[List[Tuple[int, int]]] = None,
        padding_px: int = 3
    ) -> np.ndarray:
        """
        Creates a binary mask (1 = text to exclude, 0 = keep musical notation).
        Protects staff lines while masking lyrics, dynamic words, and annotations.
        """
        h_px, w_px = image_shape[:2]
        mask = np.zeros((h_px, w_px), dtype=np.uint8)

        for item in ocr_items:
            # We exclude headers, lyrics, margin labels, directives, and measure numbers
            px0, py0, px1, py1 = item.bbox_px
            px0 = max(0, px0 - padding_px)
            py0 = max(0, py0 - padding_px)
            px1 = min(w_px, px1 + padding_px)
            py1 = min(h_px, py1 + padding_px)

            # Check if this box directly overlaps a staff line core
            overlaps_staff = False
            if staff_y_ranges_px:
                for s_top, s_bot in staff_y_ranges_px:
                    # If strictly inside staff lines (e.g. text in staff), only mask if high confidence text
                    if not (py1 < s_top or py0 > s_bot):
                        overlaps_staff = True
                        break

            # If it's pure lyrics or header outside staff, mask completely
            if not overlaps_staff or item.zone in ("header", "lyrics", "measure_number"):
                mask[py0:py1, px0:px1] = 1

        return mask
