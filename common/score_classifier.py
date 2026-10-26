from enum import Enum
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import pymupdf

logger = logging.getLogger("common.score_classifier")

# Common Music Font Identifiers (SMuFL and legacy music typesetting fonts)
MUSIC_FONT_KEYWORDS = [
    "maestro", "bravura", "opus", "leland", "petrucci", "sonata",
    "aloisen", "helsinki", "musescore", "finale", "dorico", "sibelius",
    "engraver", "jazz", "broadway", "beethoven", "goldenage", "gonville"
]

# Standard SMuFL Codepoints
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


class ScoreSourceType(str, Enum):
    BORN_DIGITAL_SMUFL = "born_digital_smufl"
    BORN_DIGITAL_VECTOR = "born_digital_vector"
    PAPER_SCAN = "paper_scan"


class ScoreBifurcationClassifier:
    """
    Intelligent Preflight Ingestion Classifier for Sheet Music PDFs:
    Bifurcates incoming scores into:
    1. BORN_DIGITAL_SMUFL: Direct digital exports containing music font glyphs (Dorico, MuseScore, Finale, Sibelius).
       Route to: Deterministic Vector SMuFL Scraper (100% accuracy, ~150ms).
    2. BORN_DIGITAL_VECTOR: Digital vector PDFs with bezier curves/lines but non-standard fonts.
       Route to: Geometric vector parser.
    3. PAPER_SCAN: Scanned paper, photocopies, or rasterized images.
       Route to: Two-Stream Inpainting + Crop-Level Local VLM (Ollama Qwen2.5-VL) + Verovio Visual Diff.
    """

    @classmethod
    def classify_pdf(cls, pdf_path: Path) -> Dict[str, Any]:
        """
        Inspects font tables, text spans, vector drawing commands, and raster image coverage.
        Returns detailed classification telemetry.
        """
        result = {
            "pdf_path": str(pdf_path),
            "source_type": ScoreSourceType.PAPER_SCAN.value,
            "confidence": 0.5,
            "has_music_fonts": False,
            "smufl_noteheads_detected": 0,
            "vector_drawings_count": 0,
            "raster_images_count": 0,
            "page_count": 0,
            "detected_music_fonts": [],
            "reasons": []
        }

        try:
            doc = pymupdf.open(str(pdf_path))
            result["page_count"] = len(doc)
            if len(doc) == 0:
                result["reasons"].append("Empty PDF document.")
                return result

            total_drawings = 0
            total_images = 0
            total_smufl_glyphs = 0
            detected_music_fonts = set()
            pages_dominated_by_images = 0

            # Analyze up to first 3 pages
            sample_pages = min(3, len(doc))
            for p_idx in range(sample_pages):
                page = doc[p_idx]
                p_rect = page.rect
                page_area = max(1.0, float(p_rect.width * p_rect.height))

                # 1. Count drawing commands (staff lines, barlines, stems)
                drawings = page.get_drawings()
                total_drawings += len(drawings)

                # 2. Inspect font names
                fonts = page.get_fonts()
                for f in fonts:
                    font_name = (f[3] or "").lower()
                    for kw in MUSIC_FONT_KEYWORDS:
                        if kw in font_name:
                            detected_music_fonts.add(f[3])
                            break

                # 3. Check for SMuFL glyphs in text rawdict
                raw = page.get_text("rawdict")
                for b in raw.get("blocks", []):
                    for l in b.get("lines", []):
                        for s in l.get("spans", []):
                            for c in s.get("chars", []):
                                ch_val = ord(c.get("c", "\x00"))
                                if ch_val in SMUFL_NOTEHEADS or ch_val in SMUFL_RESTS or ch_val in (SMUFL_G_CLEF, SMUFL_F_CLEF, SMUFL_C_CLEF):
                                    total_smufl_glyphs += 1

                # 4. Check image coverage
                imgs = page.get_images()
                total_images += len(imgs)
                image_area_sum = 0.0
                for img_info in imgs:
                    xref = img_info[0]
                    # Estimate image rect
                    img_rects = page.get_image_rects(xref)
                    for r in img_rects:
                        image_area_sum += float(r.width * r.height)

                if image_area_sum / page_area >= 0.70:
                    pages_dominated_by_images += 1

            doc.close()

            result["vector_drawings_count"] = total_drawings
            result["raster_images_count"] = total_images
            result["smufl_noteheads_detected"] = total_smufl_glyphs
            result["detected_music_fonts"] = list(detected_music_fonts)
            result["has_music_fonts"] = len(detected_music_fonts) > 0

            avg_drawings = total_drawings / sample_pages

            # Classification Logic
            if total_smufl_glyphs >= 3 or (len(detected_music_fonts) > 0 and avg_drawings >= 50):
                result["source_type"] = ScoreSourceType.BORN_DIGITAL_SMUFL.value
                result["confidence"] = 0.99
                result["reasons"].append(
                    f"Born-Digital SMuFL: Found {total_smufl_glyphs} SMuFL music glyphs, "
                    f"{len(detected_music_fonts)} music fonts ({list(detected_music_fonts)}), and {total_drawings} vector lines."
                )
            elif avg_drawings >= 100 and pages_dominated_by_images == 0:
                result["source_type"] = ScoreSourceType.BORN_DIGITAL_VECTOR.value
                result["confidence"] = 0.90
                result["reasons"].append(
                    f"Born-Digital Vector: Found {total_drawings} vector drawings with zero full-page raster backgrounds."
                )
            else:
                result["source_type"] = ScoreSourceType.PAPER_SCAN.value
                conf = 0.95 if pages_dominated_by_images > 0 else 0.85
                result["confidence"] = conf
                result["reasons"].append(
                    f"Paper Scan: Raster-dominated ({pages_dominated_by_images}/{sample_pages} pages covered by images), "
                    f"drawings={total_drawings}, smufl_glyphs={total_smufl_glyphs}."
                )

        except Exception as e:
            logger.warning(f"Error classifying PDF '{pdf_path}': {e}")
            result["reasons"].append(f"Classification failed with error: {e}")

        return result

    @classmethod
    def is_born_digital(cls, pdf_path: Path) -> bool:
        """Convenience method returning True if PDF is born-digital."""
        info = cls.classify_pdf(pdf_path)
        return info["source_type"] in (
            ScoreSourceType.BORN_DIGITAL_SMUFL.value,
            ScoreSourceType.BORN_DIGITAL_VECTOR.value
        )
