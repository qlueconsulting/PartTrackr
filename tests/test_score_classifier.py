import pytest
from pathlib import Path
from common.score_classifier import ScoreBifurcationClassifier, ScoreSourceType


def test_classify_caroling_born_digital():
    pdf_path = Path("tests/fixtures/Caroling_Final.pdf")
    assert pdf_path.exists(), "Caroling fixture missing"

    result = ScoreBifurcationClassifier.classify_pdf(pdf_path)
    assert result["source_type"] == ScoreSourceType.BORN_DIGITAL_SMUFL.value
    assert result["confidence"] >= 0.95
    assert result["has_music_fonts"] is True
    assert any("Maestro" in f for f in result["detected_music_fonts"])
    assert result["vector_drawings_count"] > 100
    assert ScoreBifurcationClassifier.is_born_digital(pdf_path) is True


def test_classify_scanned_choir_score():
    pdf_path = Path("tests/fixtures/scanned_choir_score.pdf")
    if not pdf_path.exists():
        pytest.skip("Scanned choir fixture missing")

    result = ScoreBifurcationClassifier.classify_pdf(pdf_path)
    assert result["source_type"] == ScoreSourceType.PAPER_SCAN.value
    assert result["confidence"] >= 0.85
    assert result["raster_images_count"] >= 1
    assert ScoreBifurcationClassifier.is_born_digital(pdf_path) is False
