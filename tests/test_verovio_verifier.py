import pytest
import numpy as np
from pathlib import Path
from common.verovio_verifier import VerovioVisualDiffer


SAMPLE_MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Vocal</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration>
        <type>whole</type>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_verovio_toolkit_is_available():
    """Verify that Verovio is installed and initializes cleanly."""
    assert VerovioVisualDiffer.is_available() is True


def test_verovio_render_musicxml_to_pixmap():
    """Verify that MusicXML renders to a valid 2D/3D numpy array."""
    img = VerovioVisualDiffer.render_musicxml_to_pixmap(SAMPLE_MUSICXML, scale=40, dpi=150)
    assert img is not None
    assert isinstance(img, np.ndarray)
    assert img.shape[0] > 50  # Height
    assert img.shape[1] > 50  # Width


def test_verovio_verify_system_crop():
    """Verify visual diff comparison against a synthetic crop."""
    # Create synthetic original crop with some black pixels
    synthetic_crop = np.full((200, 600, 3), 255, dtype=np.uint8)
    synthetic_crop[90:110, 200:300] = 0  # Black block representing notes

    result = VerovioVisualDiffer.verify_system_crop(SAMPLE_MUSICXML, synthetic_crop)
    assert result["rendered_available"] is True
    assert result["match_score"] > 0.0
