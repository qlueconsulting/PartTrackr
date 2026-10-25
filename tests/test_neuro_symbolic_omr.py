import copy
from fractions import Fraction
from pathlib import Path
import tempfile
import pytest

import music21
from music21 import stream, note, chord, meter, tempo, clef, layout, metadata

from common.cism_schema import (
    ScoreCISM, SystemData, MeasureData, StaffInfo, TrackData, NoteElement, BoundingBox
)
from common.learning_store import LearningManager, ScoreStyleFingerprint, StyleBlueprint
from common.loopback_verifier import LoopBackVerifier
from common.music_theory_engine import MusicTheoryEngine
from services.omr_ai_svc.audiveris_engine import AudiverisEngine, _natural_sort_key
from services.omr_ai_svc.surgical_repair import SurgicalMeasureRepair
from services.voice_router_svc.router_engine import VoiceRouterEngine
from services.decoder_xml_svc.xml_compiler import XMLCompiler
from services.decoder_xml_svc.midi_generator import MIDIGenerator


def test_natural_sort_key():
    """Verify natural numerical sorting for multi-movement scores (mvt1, mvt2, ..., mvt10)."""
    raw_names = ["mvt1.mxl", "mvt10.mxl", "mvt2.mxl", "mvt3.mxl", "mvt20.mxl"]
    paths = [Path(p) for p in raw_names]
    sorted_paths = sorted(paths, key=_natural_sort_key)
    sorted_names = [p.name for p in sorted_paths]
    assert sorted_names == ["mvt1.mxl", "mvt2.mxl", "mvt3.mxl", "mvt10.mxl", "mvt20.mxl"]


def test_audiveris_movement_stitching_and_piano_anchoring():
    """Verify that multi-movement scores are stitched with bottom-up piano accompaniment anchoring."""
    # Create two movements: Movement 1 (2 measures) and Movement 2 (2 measures)
    # Each movement has 3 parts: Top vocal staff (with lyrics) + Bottom 2 piano staves (no lyrics)
    mvt1 = stream.Score()
    p_voc1 = stream.Part(id="Voc1")
    p_rh1 = stream.Part(id="PnoRH1")
    p_lh1 = stream.Part(id="PnoLH1")

    for i in range(1, 3):
        m_v = stream.Measure(number=i)
        n = note.Note("C5", quarterLength=4.0)
        n.lyric = "Sing"
        m_v.append(n)
        p_voc1.append(m_v)

        m_rh = stream.Measure(number=i)
        m_rh.append(note.Note("G4", quarterLength=4.0))
        p_rh1.append(m_rh)

        m_lh = stream.Measure(number=i)
        m_lh.append(note.Note("C3", quarterLength=4.0))
        p_lh1.append(m_lh)

    mvt1.append(p_voc1)
    mvt1.append(p_rh1)
    mvt1.append(p_lh1)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir)
        f1 = tmp_p / "mvt1.xml"
        f2 = tmp_p / "mvt2.xml"
        mvt1.write("musicxml", fp=str(f1))
        mvt1.write("musicxml", fp=str(f2))

        stitched = AudiverisEngine._stitch_movements(
            [f1, f2],
            pdf_path=Path("choral_piece.pdf"),
            layout_data={"has_piano": True},
            score_hints={"time_signature": "4/4", "tempo_bpm": 120.0, "accompaniment_type": "piano"}
        )

        parts = list(stitched.parts)
        # Should have Vocal parts + Piano_RH + Piano_LH
        part_names = [p.id for p in parts]
        assert "Piano_RH" in part_names
        assert "Piano_LH" in part_names
        assert "Vocal_1" in part_names

        # Total stitched measures should be 4 (2 + 2)
        p_rh = next(p for p in parts if p.id == "Piano_RH")
        measures = list(p_rh.getElementsByClass(stream.Measure))
        assert len(measures) == 4
        assert [m.number for m in measures] == [1, 2, 3, 4]


def test_audiveris_vertical_system_split_remerging():
    """Verify that vertically split movements (vocal-only + piano-only) are re-merged into the same measures."""
    # When Audiveris encounters a complex score, it sometimes outputs vocal staves in mvt1 and piano in mvt2
    mvt1_vocal = stream.Score()
    p_v = stream.Part(id="Vocal")
    for i in range(1, 3):
        m = stream.Measure(number=i)
        n = note.Note("E4", quarterLength=4.0)
        n.lyric = "Gloria"
        m.append(n)
        p_v.append(m)
    mvt1_vocal.append(p_v)

    mvt2_piano = stream.Score()
    p_rh = stream.Part(id="Piano_RH")
    p_lh = stream.Part(id="Piano_LH")
    for i in range(1, 3):
        m_rh = stream.Measure(number=i)
        m_rh.append(note.Note("G4", quarterLength=4.0))
        p_rh.append(m_rh)

        m_lh = stream.Measure(number=i)
        m_lh.append(note.Note("C3", quarterLength=4.0))
        p_lh.append(m_lh)
    mvt2_piano.append(p_rh)
    mvt2_piano.append(p_lh)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir)
        f1 = tmp_p / "mvt1_vocal.xml"
        f2 = tmp_p / "mvt2_piano.xml"
        mvt1_vocal.write("musicxml", fp=str(f1))
        mvt2_piano.write("musicxml", fp=str(f2))

        stitched = AudiverisEngine._stitch_movements(
            [f1, f2],
            pdf_path=Path("gloria.pdf"),
            layout_data={"has_piano": True},
            score_hints={"time_signature": "4/4", "tempo_bpm": 100.0, "accompaniment_type": "piano"}
        )

        parts = list(stitched.parts)
        p_rh = next(p for p in parts if p.id == "Piano_RH")
        p_v = next(p for p in parts if "Vocal" in p.id)

        # They should be merged vertically into 2 measures, NOT appended to 4 measures!
        assert len(list(p_rh.getElementsByClass(stream.Measure))) == 2
        assert len(list(p_v.getElementsByClass(stream.Measure))) == 2


def test_two_step_staff_decryption_and_polyphony():
    """Verify two-step staff decryption (piano brace/labels, vocal clef fallback) and polyphonic voice splitting."""
    staves = [
        # Staff 0: Top vocal staff (unlabelled, treble clef) -> Women (SA)
        StaffInfo(staff_id="st0", index=0, clef="treble", bracket_type="bracket", role="vocal", y_top=10, y_bot=30, has_lyrics=True),
        # Staff 1: Bottom vocal staff (unlabelled, bass clef) -> Men (TB)
        StaffInfo(staff_id="st1", index=1, clef="bass", bracket_type="bracket", role="vocal", y_top=40, y_bot=60, has_lyrics=True),
        # Staff 2 & 3: Piano staves (brace)
        StaffInfo(staff_id="st2", index=2, clef="treble", bracket_type="brace", role="piano_rh", y_top=70, y_bot=90, has_lyrics=False),
        StaffInfo(staff_id="st3", index=3, clef="bass", bracket_type="brace", role="piano_lh", y_top=100, y_bot=120, has_lyrics=False),
    ]

    # Measure with polyphonic dyad chords on st0 (Soprano C5, Alto G4) and st1 (Tenor E3, Bass C3)
    raw_staves = {
        "st0": TrackData(
            track_name="st0",
            clef="treble",
            elements=[
                NoteElement(pitch="C5", duration_quarters=4.0, duration_type="whole", offset_quarters=0.0, is_rest=False, is_chord=True, chord_pitches=["G4", "C5"], lyric="Peace")
            ]
        ),
        "st1": TrackData(
            track_name="st1",
            clef="bass",
            elements=[
                NoteElement(pitch="C3", duration_quarters=4.0, duration_type="whole", offset_quarters=0.0, is_rest=False, is_chord=True, chord_pitches=["C3", "E3"], lyric="Peace")
            ]
        ),
        "st2": TrackData(track_name="st2", clef="treble", elements=[NoteElement(pitch="E4", duration_quarters=4.0, duration_type="whole", offset_quarters=0.0)]),
        "st3": TrackData(track_name="st3", clef="bass", elements=[NoteElement(pitch="A2", duration_quarters=4.0, duration_type="whole", offset_quarters=0.0)]),
    }

    cism = ScoreCISM(
        score_id="choral_test",
        title="Peace Choral",
        composer="Tester",
        page_count=1,
        total_systems=1,
        total_measures=1,
        has_piano=True,
        systems=[
            SystemData(
                system_index=0,
                page_num=1,
                bounding_box=BoundingBox(x=0, y=0, w=612, h=792),
                staves=staves,
                measures=[
                    MeasureData(
                        measure_number=1,
                        time_signature="4/4",
                        tempo_bpm=80.0,
                        quarter_length=4.0,
                        raw_staves=raw_staves
                    )
                ]
            )
        ]
    )

    routed = VoiceRouterEngine.route_score(cism)
    m1 = routed.systems[0].measures[0]

    # Check that Soprano receives the top pitch (C5) and Alto receives the lower pitch (G4)
    assert any(el.pitch == "C5" for el in m1.tracks["soprano_1"].elements)
    assert any(el.pitch == "G4" for el in m1.tracks["alto_1"].elements)

    # Check that Tenor receives top male pitch (E3) and Bass receives bottom male pitch (C3)
    assert any(el.pitch == "E3" for el in m1.tracks["tenor_1"].elements)
    assert any(el.pitch == "C3" for el in m1.tracks["bass_1"].elements)

    # Both vocal parts preserve the lyric syllable
    assert any(el.lyric == "Peace" for el in m1.tracks["soprano_1"].elements)
    assert any(el.lyric == "Peace" for el in m1.tracks["bass_1"].elements)


def test_surgical_measure_repair_and_music_theory():
    """Verify that rhythmic anomalies are detected and repaired through beat-grid quantization."""
    # A defective measure where note durations only add up to 2.5ql in a 4/4 bar (4.0ql expected)
    defective_elements = [
        NoteElement(pitch="D4", duration_quarters=1.0, duration_type="quarter", offset_quarters=0.0),
        NoteElement(pitch="F#4", duration_quarters=1.5, duration_type="dotted_quarter", offset_quarters=1.0),
    ]
    track = TrackData(track_name="st0", clef="treble", elements=defective_elements)
    m = MeasureData(measure_number=5, time_signature="4/4", quarter_length=4.0, raw_staves={"st0": track})

    # Run surgical repair (without external image, applies deterministic music theory beat-grid solver)
    repaired = SurgicalMeasureRepair.repair_anomalous_measure(
        m=m,
        staff_id="st0",
        track=track,
        key_fifths=2,
        staff_role="vocal"
    )

    # Sum of repaired duration quarters must strictly equal 4.0ql
    total_repaired_ql = sum(el.duration_quarters for el in repaired)
    assert abs(total_repaired_ql - 4.0) < 0.001
    # Pitches must be preserved
    active_pitches = [el.pitch for el in repaired if not el.is_rest]
    assert "D4" in active_pitches
    assert "F#4" in active_pitches


def test_loopback_verifier_invariant_enforcement():
    """Verify that user-verified AI Helps ground-truth facts override any OMR discrepancies."""
    raw_staves = {
        "st0": TrackData(track_name="st0", clef="treble", elements=[NoteElement(pitch="A4", duration_quarters=3.0, duration_type="dotted_half", is_rest=False)])
    }
    cism = ScoreCISM(
        score_id="loopback_test",
        title="LoopBack Song",
        composer="Tester",
        page_count=1,
        total_systems=1,
        total_measures=1,
        has_piano=False,
        systems=[
            SystemData(
                system_index=0,
                page_num=1,
                bounding_box=BoundingBox(x=0, y=0, w=100, h=100),
                staves=[StaffInfo(staff_id="st0", index=0, clef="treble", bracket_type="none", role="vocal", y_top=10, y_bot=30)],
                measures=[
                    MeasureData(
                        measure_number=1,
                        time_signature="4/4", # Drifting OMR value
                        quarter_length=4.0,
                        raw_staves=raw_staves
                    )
                ]
            )
        ]
    )

    # User verifies in AI helps that the time signature is actually 3/4
    user_hints = {"time_signature": "3/4", "tempo_bpm": 96.0}
    reconciled, report = LoopBackVerifier.verify_and_reconcile(cism, user_hints)

    m1 = reconciled.systems[0].measures[0]
    assert m1.time_signature == "3/4"
    assert m1.quarter_length == 3.0
    assert report["verified"] is True
    assert report["overall_status"] == "MATCH"


def test_partitioned_musicxml_and_midi_generation():
    """Verify that compiler exports score.musicxml, score_vocals.musicxml, score_piano.musicxml, and rehearsal MIDIs."""
    staves = [
        StaffInfo(staff_id="st0", index=0, clef="treble", bracket_type="bracket", role="vocal", y_top=10, y_bot=30, has_lyrics=True),
        StaffInfo(staff_id="st1", index=1, clef="treble", bracket_type="brace", role="piano_rh", y_top=40, y_bot=60, has_lyrics=False),
        StaffInfo(staff_id="st2", index=2, clef="bass", bracket_type="brace", role="piano_lh", y_top=70, y_bot=90, has_lyrics=False),
    ]

    cism = ScoreCISM(
        score_id="partition_test",
        title="Partitioned Choral",
        composer="Tester",
        page_count=1,
        total_systems=1,
        total_measures=2,
        has_piano=True,
        systems=[
            SystemData(
                system_index=0,
                page_num=1,
                bounding_box=BoundingBox(x=0, y=0, w=612, h=792),
                staves=staves,
                measures=[
                    MeasureData(
                        measure_number=1,
                        time_signature="4/4",
                        tempo_bpm=120.0,
                        quarter_length=4.0,
                        raw_staves={
                            "st0": TrackData(track_name="st0", clef="treble", elements=[NoteElement(pitch="C5", duration_quarters=4.0, duration_type="whole", offset_quarters=0.0, lyric="Hymn")]),
                            "st1": TrackData(track_name="st1", clef="treble", elements=[NoteElement(pitch="E4", duration_quarters=4.0, duration_type="whole", offset_quarters=0.0)]),
                            "st2": TrackData(track_name="st2", clef="bass", elements=[NoteElement(pitch="C3", duration_quarters=4.0, duration_type="whole", offset_quarters=0.0)]),
                        }
                    ),
                    MeasureData(
                        measure_number=2,
                        time_signature="4/4",
                        tempo_bpm=120.0,
                        quarter_length=4.0,
                        raw_staves={
                            "st0": TrackData(track_name="st0", clef="treble", elements=[NoteElement(pitch="D5", duration_quarters=4.0, duration_type="whole", offset_quarters=0.0, lyric="Tune")]),
                            "st1": TrackData(track_name="st1", clef="treble", elements=[NoteElement(pitch="F4", duration_quarters=4.0, duration_type="whole", offset_quarters=0.0)]),
                            "st2": TrackData(track_name="st2", clef="bass", elements=[NoteElement(pitch="D3", duration_quarters=4.0, duration_type="whole", offset_quarters=0.0)]),
                        }
                    )
                ]
            )
        ]
    )

    routed = VoiceRouterEngine.route_score(cism)

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_p = Path(tmp_dir)
        # 1. Compile MusicXML
        main_xml, piano_xml, vocals_xml, stems, summary = XMLCompiler.compile_score(routed, out_p)
        assert main_xml.exists()
        assert piano_xml.exists()
        assert vocals_xml.exists()
        assert "score.musicxml" in main_xml.name
        assert "score_piano.musicxml" in piano_xml.name
        assert "score_vocals.musicxml" in vocals_xml.name

        # 2. Compile MIDI
        main_mid, piano_mid, vocals_mid, midi_stems, sync_map = MIDIGenerator.compile_midi_and_sync_map(routed, out_p)
        assert main_mid.exists()
        assert piano_mid.exists()
        assert vocals_mid.exists()
        assert sync_map.exists()
        assert "score_11ch.mid" in main_mid.name
        assert "score_piano.mid" in piano_mid.name
        assert "score_vocals.mid" in vocals_mid.name


def test_audiveris_brace_and_clef_partitioning_rules():
    """
    Verify exact rule:
    1. Curved braces or labels ('piano' / 'keyboard') identify piano part (always exactly 2 staves: RH Treble + LH Bass).
    2. Remaining unlabeled staves are partitioned: Treble clef -> women parts, Bass clef -> male parts.
    3. Partitioned into two synchronized MusicXMLs (score_piano.musicxml and score_vocals.musicxml).
    """
    # Create a 4-staff score:
    # Staff 0: Unlabeled Treble clef (Women)
    # Staff 1: Unlabeled Bass clef (Men)
    # Staff 2: Piano RH (Treble) in brace
    # Staff 3: Piano LH (Bass) in brace
    sc = stream.Score()
    p_w = stream.Part(id="P1") # Unlabeled women
    p_m = stream.Part(id="P2") # Unlabeled men
    p_prh = stream.Part(id="P3") # Piano RH
    p_plh = stream.Part(id="P4") # Piano LH

    p_w.insert(0, clef.TrebleClef())
    p_m.insert(0, clef.BassClef())
    p_prh.insert(0, clef.TrebleClef())
    p_plh.insert(0, clef.BassClef())

    for m_num in range(1, 4):
        # Women
        mw = stream.Measure(number=m_num)
        mw.append(note.Note("G4", quarterLength=4.0))
        p_w.append(mw)
        # Men
        mm = stream.Measure(number=m_num)
        mm.append(note.Note("D3", quarterLength=4.0))
        p_m.append(mm)
        # Piano RH
        mprh = stream.Measure(number=m_num)
        mprh.append(note.Note("B4", quarterLength=4.0))
        p_prh.append(mprh)
        # Piano LH
        mplh = stream.Measure(number=m_num)
        mplh.append(note.Note("G2", quarterLength=4.0))
        p_plh.append(mplh)

    sc.append(p_w)
    sc.append(p_m)
    sc.append(p_prh)
    sc.append(p_plh)

    # Add curly brace grouping for P3 and P4
    sc.append(layout.StaffGroup([p_prh, p_plh], symbol="brace", name="Keyboard"))

    cism = AudiverisEngine._music21_score_to_cism(
        score=sc,
        pdf_path=Path("choral_anthem.pdf"),
        layout_data={"has_piano": True},
        score_hints={"time_signature": "4/4", "tempo_bpm": 100.0}
    )

    assert cism.has_piano is True
    staves = cism.systems[0].staves
    assert len(staves) == 4

    # Staff 0: Unlabeled Treble -> Women
    assert staves[0].role == "vocal_women"
    assert staves[0].bracket_type == "bracket"
    assert staves[0].clef == "treble"

    # Staff 1: Unlabeled Bass -> Men
    assert staves[1].role == "vocal_men"
    assert staves[1].bracket_type == "bracket"
    assert staves[1].clef == "bass"

    # Staff 2 & 3: Braced Piano -> exactly 2 staves (RH Treble + LH Bass)
    assert staves[2].role == "piano_rh"
    assert staves[2].bracket_type == "brace"
    assert staves[2].clef == "treble"

    assert staves[3].role == "piano_lh"
    assert staves[3].bracket_type == "brace"
    assert staves[3].clef == "bass"

    # Voice route and compile partitioned XML
    routed = VoiceRouterEngine.route_score(cism)
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_p = Path(tmp_dir)
        main_xml, piano_xml, vocals_xml, stems, summary = XMLCompiler.compile_score(routed, out_p)

        assert piano_xml.exists()
        assert vocals_xml.exists()
        assert len(summary) == 3  # Exactly 3 synchronized measures
        assert [m["measure_number"] for m in summary] == [1, 2, 3]


def test_two_pass_top_down_macro_layout_and_isolated_staff_reading():
    """
    Verify the Two-Pass Top-Down Architectural Paradigm:
    Pass 1: Full-page layout identifies and locks part roles (piano is exactly 2 staves, vocal staves follow clefs/labels)
            and outputs isolated per-staff measure crops.
    Pass 2: Revisit line-by-line along isolated staff tracks so notes/stems on piano never contaminate vocal staves.
    """
    from services.pdf_layout_svc.layout_engine import PDFLayoutEngine
    from services.omr_ai_svc.geometric_omr_engine import GeometricOMREngine
    from services.omr_ai_svc.hybrid_fusion_engine import HybridOMRFusionEngine

    fixture_pdf = Path("tests/fixtures/scanned_choir_score.pdf")
    if not fixture_pdf.exists():
        pytest.skip("Scanned score fixture not found")

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        hints = {
            "staves_per_system": 3,
            "time_signature": "6/8",
            "choral_voicing": "Tenor_Bass",
            "accompaniment_type": "piano",
        }
        # Pass 1: Macro-Layout
        layout_data = PDFLayoutEngine.process_pdf(fixture_pdf, out_dir, dpi=150, score_hints=hints)
        assert len(layout_data["systems"]) >= 1

        sys0 = layout_data["systems"][0]
        staves = sys0["staves"]
        assert len(staves) == 3

        # Hard rules verification:
        assert staves[0]["role"] == "vocal_men"
        assert staves[0]["bracket_type"] == "none"
        assert staves[1]["role"] == "piano_rh"
        assert staves[1]["bracket_type"] == "brace"
        assert staves[2]["role"] == "piano_lh"
        assert staves[2]["bracket_type"] == "brace"

        # Verify isolated staff crops are present for every measure
        measures = sys0["measures"]
        assert len(measures) >= 1
        m0 = measures[0]
        assert "staff_crop_paths" in m0
        assert len(m0["staff_crop_paths"]) == 3
        for st_info in staves:
            st_id = st_info["staff_id"]
            assert st_id in m0["staff_crop_paths"]
            st_crop_file = Path(m0["staff_crop_paths"][st_id])
            assert st_crop_file.exists()
            assert st_crop_file.stat().st_size > 0

        # Pass 2: Line-by-Line Track Revisit
        cism = HybridOMRFusionEngine.extract_cism(
            layout_data=layout_data,
            score_hints=hints
        )
        assert cism is not None
        assert len(cism.systems) >= 1
        cism_sys0 = cism.systems[0]
        cism_m0 = cism_sys0.measures[0]

        # Verify tracks were populated for all 3 isolated staves without cross-staff bleeding
        for st_info in staves:
            st_id = st_info["staff_id"]
            assert st_id in cism_m0.raw_staves
            track = cism_m0.raw_staves[st_id]
            assert len(track.elements) >= 1
            assert track.clef == st_info["clef"]

        # Voice route and verify partitioned outputs
        routed = VoiceRouterEngine.route_score(cism, score_hints=hints)
        xml_dir = out_dir / "xml"
        main_xml, piano_xml, vocals_xml, stems, summary = XMLCompiler.compile_score(routed, xml_dir)
        assert piano_xml.exists()
        assert vocals_xml.exists()
        assert len(summary) >= 1


def test_cross_part_measure_number_and_rehearsal_alignment():
    """
    Verify that when piecing parts back together:
    1. Parts with delayed entry (e.g. choir entering at measure 5 after piano intro) align on exact measure numbers,
       never shifting subsequent measures out of phase.
    2. Rehearsal marks (e.g. [A], [B]) synchronize across parts and compile into MusicXML.
    3. score_piano.musicxml and score_vocals.musicxml remain strictly synchronized measure by measure.
    """
    # Create a 6-measure score where:
    # Piano RH & LH play measures 1 to 6
    # Choir (Vocal) rests for measures 1..4 and enters at Measure 5 (labeled Rehearsal [A])
    sc = stream.Score()

    p_choir = stream.Part(id="Choir")
    p_choir.partName = "Choir"
    p_prh = stream.Part(id="Piano_RH")
    p_prh.partName = "Piano RH"
    p_plh = stream.Part(id="Piano_LH")
    p_plh.partName = "Piano LH"

    # Piano plays measures 1 to 6
    for m_i in range(1, 7):
        m_rh = stream.Measure(number=m_i)
        m_rh.append(note.Note("C5", quarterLength=4.0))
        if m_i == 5:
            m_rh.insert(0, music21.expressions.RehearsalMark("A"))
        p_prh.append(m_rh)

        m_lh = stream.Measure(number=m_i)
        m_lh.append(note.Note("C3", quarterLength=4.0))
        if m_i == 5:
            m_lh.insert(0, music21.expressions.RehearsalMark("A"))
        p_plh.append(m_lh)

    # Choir only has measures 5 and 6 (Audiveris exports only active measures when voices enter)
    for m_i in [5, 6]:
        m_ch = stream.Measure(number=m_i)
        n = note.Note("G4", quarterLength=4.0)
        n.lyric = "Hallelujah"
        m_ch.append(n)
        m_ch.insert(0, music21.expressions.RehearsalMark("A"))
        p_choir.append(m_ch)

    sc.append(p_choir)
    sc.append(p_prh)
    sc.append(p_plh)

    # Piece parts back together into CISM
    cism = AudiverisEngine._music21_score_to_cism(
        score=sc,
        pdf_path=Path("choral_anthem.pdf"),
        layout_data={"has_piano": True},
        score_hints={"time_signature": "4/4", "tempo_bpm": 100.0}
    )

    # Must contain exactly 6 synchronized measures
    all_meas = cism.all_measures()
    assert len(all_meas) == 6
    assert [m.measure_number for m in all_meas] == [1, 2, 3, 4, 5, 6]

    # Measures 1..4: Choir must have clean rests, Piano must have notes
    for m_idx in range(4):
        m = all_meas[m_idx]
        choir_track = m.raw_staves["st_0"]
        assert all(el.is_rest for el in choir_track.elements), f"Choir should rest in measure {m.measure_number}"
        piano_rh_track = m.raw_staves["st_1"]
        assert any(not el.is_rest for el in piano_rh_track.elements), f"Piano RH should play in measure {m.measure_number}"

    # Measure 5 (Rehearsal [A]): Choir and Piano must BOTH be active and aligned
    m5 = all_meas[4]
    assert m5.measure_number == 5
    assert m5.rehearsal_mark == "A"
    choir_m5 = m5.raw_staves["st_0"]
    assert any(el.pitch == "G4" for el in choir_m5.elements)
    assert any(el.lyric == "Hallelujah" for el in choir_m5.elements)
    piano_m5 = m5.raw_staves["st_1"]
    assert any(el.pitch == "C5" for el in piano_m5.elements)

    # Route score and verify partitioned XML synchronization
    routed = VoiceRouterEngine.route_score(cism)
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_p = Path(tmp_dir)
        main_xml, piano_xml, vocals_xml, stems, summary = XMLCompiler.compile_score(routed, out_p)

        assert piano_xml.exists()
        assert vocals_xml.exists()
        assert len(summary) == 6

        # Verify rehearsal mark appears in summary at measure 5
        m5_summary = next(item for item in summary if item["measure_number"] == 5)
        assert m5_summary["rehearsal_mark"] == "A"

        # Verify MIDI sync map has rehearsal mark
        mid_p, p_mid, v_mid, s_mids, sync_map_p = MIDIGenerator.compile_midi_and_sync_map(routed, out_p / "midi")
        import json
        with open(sync_map_p, "r") as f:
            sync_data = json.load(f)
        m5_sync = next(item for item in sync_data["measures"] if item["measure_number"] == 5)
        assert m5_sync["rehearsal_mark"] == "A"


def test_vertical_split_remerging_with_divergent_measure_counts():
    """Verify that vocal and piano movements with divergent measure counts merge concurrently, not serially."""
    # Vocal movement: 3 measures
    mvt_voc = stream.Score()
    p_v = stream.Part(id="Vocal")
    for i in range(1, 4):
        m = stream.Measure(number=i)
        n = note.Note("C5", quarterLength=4.0)
        n.lyric = f"Word{i}"
        m.append(n)
        p_v.append(m)
    mvt_voc.append(p_v)

    # Piano movement: 5 measures (diverges by 2 measures!)
    mvt_pno = stream.Score()
    p_rh = stream.Part(id="Piano_RH")
    p_lh = stream.Part(id="Piano_LH")
    for i in range(1, 6):
        m_rh = stream.Measure(number=i)
        m_rh.append(note.Note("E4", quarterLength=4.0))
        p_rh.append(m_rh)

        m_lh = stream.Measure(number=i)
        m_lh.append(note.Note("C3", quarterLength=4.0))
        p_lh.append(m_lh)
    mvt_pno.append(p_rh)
    mvt_pno.append(p_lh)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir)
        f_v = tmp_p / "mvt1_vocal.xml"
        f_p = tmp_p / "mvt2_piano.xml"
        mvt_voc.write("musicxml", fp=str(f_v))
        mvt_pno.write("musicxml", fp=str(f_p))

        stitched = AudiverisEngine._stitch_movements(
            [f_v, f_p],
            pdf_path=Path("choral_divergent.pdf"),
            layout_data={"has_piano": True},
            score_hints={"time_signature": "4/4", "tempo_bpm": 120.0, "accompaniment_type": "piano"}
        )

        parts = list(stitched.parts)
        p_rh_out = next(p for p in parts if p.id == "Piano_RH")
        p_v_out = next(p for p in parts if "Vocal" in p.id)

        # Must merge into max(3, 5) = 5 parallel measures, NOT 3 + 5 = 8 serial measures!
        v_meas = list(p_v_out.getElementsByClass(stream.Measure))
        p_meas = list(p_rh_out.getElementsByClass(stream.Measure))
        assert len(v_meas) == 5
        assert len(p_meas) == 5

        # In measures 1..3, vocal has notes and piano has notes (parallel synchronization)
        for i in range(3):
            assert any(isinstance(el, note.Note) for el in v_meas[i].flatten().notesAndRests)
            assert any(isinstance(el, note.Note) for el in p_meas[i].flatten().notesAndRests)

        # In measures 4..5, piano has notes and vocal has padding rests
        for i in range(3, 5):
            assert all(isinstance(el, note.Rest) for el in v_meas[i].flatten().notesAndRests)
            assert any(isinstance(el, note.Note) for el in p_meas[i].flatten().notesAndRests)


def test_vertical_split_remerging_when_piano_movement_is_first():
    """Verify that when the piano movement is exported first (idx 0), it merges with the vocal movement."""
    mvt_pno = stream.Score()
    p_rh = stream.Part(id="Piano_RH")
    p_lh = stream.Part(id="Piano_LH")
    for i in range(1, 4):
        m_rh = stream.Measure(number=i)
        m_rh.append(note.Note("G4", quarterLength=4.0))
        p_rh.append(m_rh)

        m_lh = stream.Measure(number=i)
        m_lh.append(note.Note("G2", quarterLength=4.0))
        p_lh.append(m_lh)
    mvt_pno.append(p_rh)
    mvt_pno.append(p_lh)

    mvt_voc = stream.Score()
    p_v = stream.Part(id="Vocal")
    for i in range(1, 4):
        m = stream.Measure(number=i)
        n = note.Note("D5", quarterLength=4.0)
        n.lyric = "Sing"
        m.append(n)
        p_v.append(m)
    mvt_voc.append(p_v)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir)
        # f1 is piano, f2 is vocal
        f1 = tmp_p / "mvt1_piano.xml"
        f2 = tmp_p / "mvt2_vocal.xml"
        mvt_pno.write("musicxml", fp=str(f1))
        mvt_voc.write("musicxml", fp=str(f2))

        stitched = AudiverisEngine._stitch_movements(
            [f1, f2],
            pdf_path=Path("choral_piano_first.pdf"),
            layout_data={"has_piano": True},
            score_hints={"time_signature": "4/4", "tempo_bpm": 120.0, "accompaniment_type": "piano"}
        )

        parts = list(stitched.parts)
        p_rh_out = next(p for p in parts if p.id == "Piano_RH")
        p_v_out = next(p for p in parts if "Vocal" in p.id)

        # Must merge into 3 parallel measures starting at measure 1
        assert len(list(p_rh_out.getElementsByClass(stream.Measure))) == 3
        assert len(list(p_v_out.getElementsByClass(stream.Measure))) == 3


def test_partitioned_multipage_movement_remerging():
    """Verify that partitioned movements [vocal_p1, vocal_p2, piano_p1, piano_p2] re-merge into synchronized blocks."""
    def _make_part(p_id, start_m, end_m, pitch, lyric=None):
        sc = stream.Score()
        p = stream.Part(id=p_id)
        for i in range(start_m, end_m + 1):
            m = stream.Measure(number=i)
            n = note.Note(pitch, quarterLength=4.0)
            if lyric:
                n.lyric = f"{lyric}_{i}"
            m.append(n)
            p.append(m)
        sc.append(p)
        return sc

    # 4 movements: vocal across 2 pages, piano across 2 pages
    voc_p1 = _make_part("Vocal", 1, 3, "E4", "P1")
    voc_p2 = _make_part("Vocal", 4, 6, "F4", "P2")

    pno_p1 = stream.Score()
    p_rh1 = stream.Part(id="Piano_RH")
    p_lh1 = stream.Part(id="Piano_LH")
    for i in range(1, 4):
        m_rh = stream.Measure(number=i)
        m_rh.append(note.Note("G4", quarterLength=4.0))
        p_rh1.append(m_rh)
        m_lh = stream.Measure(number=i)
        m_lh.append(note.Note("C3", quarterLength=4.0))
        p_lh1.append(m_lh)
    pno_p1.append(p_rh1)
    pno_p1.append(p_lh1)

    pno_p2 = stream.Score()
    p_rh2 = stream.Part(id="Piano_RH")
    p_lh2 = stream.Part(id="Piano_LH")
    for i in range(4, 7):
        m_rh = stream.Measure(number=i)
        m_rh.append(note.Note("A4", quarterLength=4.0))
        p_rh2.append(m_rh)
        m_lh = stream.Measure(number=i)
        m_lh.append(note.Note("D3", quarterLength=4.0))
        p_lh2.append(m_lh)
    pno_p2.append(p_rh2)
    pno_p2.append(p_lh2)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir)
        f1 = tmp_p / "score_01_vocal_p1.xml"
        f2 = tmp_p / "score_02_vocal_p2.xml"
        f3 = tmp_p / "score_03_piano_p1.xml"
        f4 = tmp_p / "score_04_piano_p2.xml"

        voc_p1.write("musicxml", fp=str(f1))
        voc_p2.write("musicxml", fp=str(f2))
        pno_p1.write("musicxml", fp=str(f3))
        pno_p2.write("musicxml", fp=str(f4))

        stitched = AudiverisEngine._stitch_movements(
            [f1, f2, f3, f4],
            pdf_path=Path("choral_partitioned.pdf"),
            layout_data={"has_piano": True},
            score_hints={"time_signature": "4/4", "tempo_bpm": 120.0, "accompaniment_type": "piano"}
        )

        parts = list(stitched.parts)
        p_rh_out = next(p for p in parts if p.id == "Piano_RH")
        p_v_out = next(p for p in parts if "Vocal" in p.id)

        v_meas = list(p_v_out.getElementsByClass(stream.Measure))
        p_meas = list(p_rh_out.getElementsByClass(stream.Measure))

        # Must merge into 6 total parallel measures (1..6)
        assert len(v_meas) == 6
        assert len(p_meas) == 6
        assert [m.number for m in v_meas] == [1, 2, 3, 4, 5, 6]
        assert [m.number for m in p_meas] == [1, 2, 3, 4, 5, 6]

        # Both vocal and piano are active simultaneously across measures 1..6
        for m_idx in range(6):
            assert any(isinstance(el, note.Note) for el in v_meas[m_idx].flatten().notesAndRests)
            assert any(isinstance(el, note.Note) for el in p_meas[m_idx].flatten().notesAndRests)


def test_piano_midi_channel_routing_and_timbre():
    """Verify that piano uses GM Program 0 (Acoustic Grand Piano) and melodic tracks avoid GM percussion channel 9."""
    from common.taxonomy import PART_METADATA
    assert PART_METADATA["piano"]["gm_program"] == 0
    assert PART_METADATA["piano"]["channel"] == 0

    # Ensure bass parts do NOT use GM Drum channel 9
    assert PART_METADATA["bass_1"]["channel"] != 9
    assert PART_METADATA["bass_2"]["channel"] != 9
    assert PART_METADATA["bass_1"]["channel"] == 10
    assert PART_METADATA["bass_2"]["channel"] == 11



