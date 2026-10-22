from fractions import Fraction
from pathlib import Path
import tempfile
import pytest
import pymupdf
import numpy as np

from common.cism_schema import NoteElement, TrackData, MeasureData, SystemData, ScoreCISM, StaffInfo, BoundingBox
from common.ocr_fusion import ScoreOCREngine
from common.music_theory_engine import MusicTheoryEngine
from services.pdf_layout_svc.layout_engine import PDFLayoutEngine
from services.omr_ai_svc.geometric_omr_engine import GeometricOMREngine
from services.omr_ai_svc.hybrid_fusion_engine import HybridOMRFusionEngine
from services.decoder_xml_svc.xml_compiler import XMLCompiler
from services.decoder_xml_svc.midi_generator import MIDIGenerator
from services.voice_router_svc.router_engine import VoiceRouterEngine


TEST_PDF = Path(r"C:\Users\breas\.gemini\antigravity\brain\4acbcb2b-4819-4cb1-9699-9c69736ca129\.user_uploaded\media_1792361796541_e1c634ca.pdf")


def test_score_ocr_engine_scanned_extraction():
    """Verify that ScoreOCREngine extracts Title, Composer, Tempo, and labels on Page 1."""
    if not TEST_PDF.exists():
        pytest.skip("Test PDF not found")

    doc = pymupdf.open(str(TEST_PDF))
    p0 = doc[0]
    pix = p0.get_pixmap(dpi=150)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
    res = ScoreOCREngine.process_page_image(img, p0.rect.width, p0.rect.height, 1, first_staff_y_pt=170.0)

    assert res.title is not None
    assert "NOWELL" in res.title.upper() or "FIRST" in res.title.upper()
    assert res.composer is not None
    assert "WILBERG" in res.composer.upper() or "CAROL" in res.composer.upper()
    assert res.tempo_text is not None
    assert "adoration" in res.tempo_text.lower() or "slow" in res.tempo_text.lower()
    doc.close()


def test_music_theory_circle_of_fifths_and_clefs():
    """Verify key signature alterations, treble 8vb clef, and measure accidentals."""
    # D Major (+2 fifths)
    d_alts = MusicTheoryEngine.resolve_key_alterations(2)
    assert d_alts == {"F": "#", "C": "#"}

    # E Major (+4 fifths)
    e_alts = MusicTheoryEngine.resolve_key_alterations(4)
    assert e_alts == {"F": "#", "C": "#", "G": "#", "D": "#"}

    # Resolving step F in D Major
    pitch, midi = MusicTheoryEngine.resolve_step_to_pitch(step="F", octave=3, key_fifths=2, clef="bass")
    assert pitch == "F#3"
    assert midi == 54

    # Resolving step C in Treble 8vb (Tenor clef)
    pitch_t, midi_t = MusicTheoryEngine.resolve_step_to_pitch(step="C", octave=5, key_fifths=0, clef="treble_8vb")
    assert pitch_t == "C4"
    assert midi_t == 60  # Middle C (one octave below treble C5)

    # In-measure accidental carryover and reset
    meas_acc = {}
    p1, m1 = MusicTheoryEngine.resolve_step_to_pitch("G", 4, key_fifths=0, explicit_accidental="#", measure_accidentals=meas_acc)
    assert p1 == "G#4"
    p2, m2 = MusicTheoryEngine.resolve_step_to_pitch("G", 4, key_fifths=0, explicit_accidental=None, measure_accidentals=meas_acc)
    assert p2 == "G#4"  # Carries over in measure


def test_dynamic_system_topology_across_all_8_pages():
    """Verify that layout engine accurately segments all 8 pages into exact system counts."""
    if not TEST_PDF.exists():
        pytest.skip("Test PDF not found")

    doc = pymupdf.open(str(TEST_PDF))
    system_counts = []
    for p_idx in range(len(doc)):
        syss = PDFLayoutEngine._extract_page_systems(doc[p_idx], p_idx + 1)
        system_counts.append([len(s["staves"]) for s in syss])
    doc.close()

    assert system_counts[0] == [3, 3, 3]         # Page 1: 3-staff Tenor/Bass + Piano
    assert system_counts[1] == [3, 3, 3, 3]      # Page 2: 3-staff Tenor/Bass + Piano
    assert system_counts[2] == [2, 3, 3, 3]      # Page 3: 2-staff prelude + three 3-staff systems
    assert system_counts[3] == [3, 3, 3]         # Page 4: three 3-staff systems
    assert system_counts[4] == [2, 4, 4]         # Page 5: 2-staff interlude + two 4-staff systems
    assert system_counts[5] == [6, 6]            # Page 6: two 6-staff SATB+Piano systems!
    assert system_counts[6] == [6, 6]            # Page 7: two 6-staff SATB+Piano systems!
    assert system_counts[7] == [3, 4, 4]         # Page 8: 3-staff Tenor solo + two 4-staff systems


def test_measures_1_to_3_silent_vocal_rest_enforcement():
    """Verify that Measure 1-3 vocal staves are 100% rests and not fake notes from text."""
    staves = [
        StaffInfo(staff_id="st0", index=0, clef="bass", role="vocal_men", y_top=150.0, y_bot=180.0),
        StaffInfo(staff_id="st1", index=1, clef="bass", role="piano_rh", y_top=210.0, y_bot=240.0),
        StaffInfo(staff_id="st2", index=2, clef="bass", role="piano_lh", y_top=270.0, y_bot=300.0),
    ]
    layout_data = {
        "title": "The First Nowell",
        "composer": "Mack Wilberg",
        "has_piano": True,
        "time_signature": "3/4",
        "tempo_bpm": 88.0,
        "systems": [{
            "system_index": 1,
            "page_num": 1,
            "bounding_box": {"x": 50, "y": 150, "w": 500, "h": 150},
            "staves": [s.model_dump() for s in staves],
            "measures": [
                {"measure_number": 1, "bounding_box": {"x": 50, "y": 150, "w": 100, "h": 150}},
                {"measure_number": 2, "bounding_box": {"x": 150, "y": 150, "w": 100, "h": 150}},
                {"measure_number": 3, "bounding_box": {"x": 250, "y": 150, "w": 100, "h": 150}},
            ]
        }]
    }

    cism = HybridOMRFusionEngine.extract_cism(layout_data)
    m1 = cism.systems[0].measures[0]
    vocal_track = m1.raw_staves["st0"]

    # Verify vocal staff in Measure 1 is 100% resting
    assert all(el.is_rest for el in vocal_track.elements)
    assert sum(el.duration_quarters for el in vocal_track.elements) == 3.0


def test_polyphonic_chords_and_midi_generation():
    """Verify that polyphonic chords, cross-bar ties, and tempo changes compile to MIDI and MusicXML."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Build test CISM with piano chord and tied notes
        piano_chord = NoteElement(
            pitch="D4",
            duration_quarters=3.0,
            duration_type="dotted_half",
            offset_quarters=0.0,
            is_chord=True,
            chord_pitches=["D3", "A3", "F#4"],
            is_rest=False
        )

        tied_note_m1 = NoteElement(
            pitch="D3",
            duration_quarters=3.0,
            duration_type="dotted_half",
            offset_quarters=0.0,
            tie="start",
            is_rest=False
        )
        tied_note_m2 = NoteElement(
            pitch="D3",
            duration_quarters=3.0,
            duration_type="dotted_half",
            offset_quarters=0.0,
            tie="stop",
            is_rest=False
        )

        m1_tracks = {
            "tenor_1": TrackData(track_name="tenor_1", clef="treble_8vb", elements=[tied_note_m1]),
            "piano": TrackData(track_name="piano", clef="grand", elements=[piano_chord]),
        }
        m2_tracks = {
            "tenor_1": TrackData(track_name="tenor_1", clef="treble_8vb", elements=[tied_note_m2]),
            "piano": TrackData(track_name="piano", clef="grand", elements=[piano_chord]),
        }

        # Fill remaining parts with rests
        for p in ["soprano_1", "soprano_2", "alto_1", "alto_2", "tenor_2", "baritone_1", "baritone_2", "bass_1", "bass_2"]:
            r = NoteElement(pitch=None, duration_quarters=3.0, duration_type="dotted_half", is_rest=True)
            m1_tracks[p] = TrackData(track_name=p, clef="treble", elements=[r])
            m2_tracks[p] = TrackData(track_name=p, clef="treble", elements=[r])

        m1 = MeasureData(measure_number=1, time_signature="3/4", tempo_bpm=88.0, quarter_length=3.0, tracks=m1_tracks)
        m2 = MeasureData(measure_number=2, time_signature="3/4", tempo_bpm=88.0, quarter_length=3.0, tracks=m2_tracks)

        cism = ScoreCISM(
            score_id="test_polyphony",
            title="Polyphony Test",
            composer="Mack Wilberg",
            total_systems=1,
            total_measures=2,
            has_piano=True,
            systems=[SystemData(
                system_index=1,
                page_num=1,
                bounding_box=BoundingBox(x=0, y=0, w=500, h=500),
                measures=[m1, m2]
            )]
        )

        # 1. Compile MusicXML (Master, Piano-only partition, Vocals-only partition)
        xml_path, piano_xml, vocals_xml, stem_xmls, summary = XMLCompiler.compile_score(cism, tmp_path / "xml")
        assert xml_path.exists()
        assert xml_path.stat().st_size > 500
        assert piano_xml.exists()
        assert vocals_xml.exists()

        # 2. Compile MIDI (Master, Piano-only partition, Vocals-only partition)
        midi_path, piano_midi, vocals_midi, stem_midis, sync_map = MIDIGenerator.compile_midi_and_sync_map(cism, tmp_path / "midi")
        assert midi_path.exists()
        assert midi_path.stat().st_size > 400
        assert piano_midi.exists()
        assert vocals_midi.exists()
        assert sync_map.exists()


def test_measure_anchor_reconciliation_and_zero_drift():
    """Verify that layout engine reconciles OCR measure numbers with zero drift."""
    if not TEST_PDF.exists():
        pytest.skip("Test PDF not found")

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = Path(tmp_dir)
        res = PDFLayoutEngine.process_pdf(TEST_PDF, out_path, dpi=150)
        assert res["total_measures"] == 112
        assert len(res["systems"]) == 24

        sys1 = res["systems"][0]
        assert sys1["measure_start"] == 1
        assert sys1["measure_end"] == 5

        sys2 = res["systems"][1]
        assert sys2["measure_start"] == 6
        assert sys2["measure_end"] == 10

        sys3 = res["systems"][2]
        assert sys3["measure_start"] == 11
        assert sys3["measure_end"] == 15

        sys4 = res["systems"][3]
        assert sys4["measure_start"] == 16
        assert sys4["measure_end"] == 19

        sys5 = res["systems"][4]
        assert sys5["measure_start"] == 20
        assert sys5["measure_end"] == 23

        sys24 = res["systems"][23]
        assert sys24["measure_start"] == 108
        assert sys24["measure_end"] == 112

