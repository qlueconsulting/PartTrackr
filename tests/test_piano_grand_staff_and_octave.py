import tempfile
from pathlib import Path
import pytest
import music21
from music21 import stream, note, clef

from common.cism_schema import (
    ScoreCISM, SystemData, MeasureData, StaffInfo, TrackData, NoteElement, BoundingBox
)
from common.music_theory_engine import MusicTheoryEngine
from services.decoder_xml_svc.xml_compiler import XMLCompiler


def test_music_theory_engine_diatonic_step_to_step_and_octave():
    """Verify analytic diatonic step resolution across wide ranges for treble and bass clefs."""
    # Treble Clef: Line 1 (bottom line, step 0) is E4
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(0, clef="treble") == ("E", 4)
    # Line 2 (step 2) is G4
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(2, clef="treble") == ("G", 4)
    # Line 5 (top line, step 8) is F5
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(8, clef="treble") == ("F", 5)
    # Below staff: step -1 is D4, step -2 is C4 (Middle C)
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(-1, clef="treble") == ("D", 4)
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(-2, clef="treble") == ("C", 4)
    # High ledger line: step 12 is C6
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(12, clef="treble") == ("C", 6)

    # Bass Clef: Line 1 (bottom line, step 0) is G2
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(0, clef="bass") == ("G", 2)
    # Line 2 (step 2) is B2
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(2, clef="bass") == ("B", 2)
    # Line 4 (step 6) is F3
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(6, clef="bass") == ("F", 3)
    # Line 5 (top line, step 8) is A3
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(8, clef="bass") == ("A", 3)
    # Above staff: step 10 is C4 (Middle C)
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(10, clef="bass") == ("C", 4)
    # Low ledger lines: step -2 is E2, step -4 is C2, step -6 is A1, step -11 is C1
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(-2, clef="bass") == ("E", 2)
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(-4, clef="bass") == ("C", 2)
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(-6, clef="bass") == ("A", 1)
    assert MusicTheoryEngine.diatonic_step_to_step_and_octave(-11, clef="bass") == ("C", 1)


def test_resolve_step_to_pitch_accurate_octaves():
    """Verify MusicTheoryEngine.resolve_step_to_pitch produces exact pitch name and MIDI numbers."""
    # Treble: step 0 (E4) -> "E4", MIDI 64
    step, oct_num = MusicTheoryEngine.diatonic_step_to_step_and_octave(0, clef="treble")
    pitch_str, midi_num = MusicTheoryEngine.resolve_step_to_pitch(step, oct_num, key_fifths=0, clef="treble")
    assert pitch_str == "E4" and midi_num == 64

    # Treble: step -2 (C4 / Middle C) -> "C4", MIDI 60
    step, oct_num = MusicTheoryEngine.diatonic_step_to_step_and_octave(-2, clef="treble")
    pitch_str, midi_num = MusicTheoryEngine.resolve_step_to_pitch(step, oct_num, key_fifths=0, clef="treble")
    assert pitch_str == "C4" and midi_num == 60

    # Bass: step 0 (G2) -> "G2", MIDI 43
    step, oct_num = MusicTheoryEngine.diatonic_step_to_step_and_octave(0, clef="bass")
    pitch_str, midi_num = MusicTheoryEngine.resolve_step_to_pitch(step, oct_num, key_fifths=0, clef="bass")
    assert pitch_str == "G2" and midi_num == 43

    # Bass: step -4 (C2) -> "C2", MIDI 36
    step, oct_num = MusicTheoryEngine.diatonic_step_to_step_and_octave(-4, clef="bass")
    pitch_str, midi_num = MusicTheoryEngine.resolve_step_to_pitch(step, oct_num, key_fifths=0, clef="bass")
    assert pitch_str == "C2" and midi_num == 36


def test_xml_compiler_piano_two_staves_with_treble_and_bass_clefs():
    """Verify that XMLCompiler exports piano with two staves (RH Treble + LH Bass) joined by a brace in score.musicxml, score_piano.musicxml, and stems/piano.musicxml."""
    cism = ScoreCISM(
        score_id="test_score_piano",
        title="Piano Grand Staff Test",
        has_piano=True,
    )

    sys1 = SystemData(
        system_index=0,
        page_num=1,
        bounding_box=BoundingBox(x=10, y=10, w=490, h=190),
        staves=[
            StaffInfo(staff_id="s_soprano", index=0, role="vocal", clef="treble", y_top=10.0, y_bot=40.0),
            StaffInfo(staff_id="s_piano_rh", index=1, role="piano_rh", clef="treble", y_top=60.0, y_bot=90.0),
            StaffInfo(staff_id="s_piano_lh", index=2, role="piano_lh", clef="bass", y_top=110.0, y_bot=140.0),
        ],
    )

    m1 = MeasureData(
        measure_number=1,
        system_index=0,
        time_signature="4/4",
        tempo_bpm=100.0,
        tracks={
            "soprano": TrackData(
                track_name="soprano",
                clef="treble",
                elements=[
                    NoteElement(pitch="C5", duration_quarters=4.0, duration_type="whole", midi_pitch=72)
                ],
            ),
            "piano_rh": TrackData(
                track_name="piano_rh",
                clef="treble",
                elements=[
                    NoteElement(pitch="E4", duration_quarters=2.0, duration_type="half", midi_pitch=64),
                    NoteElement(pitch="G4", duration_quarters=2.0, duration_type="half", midi_pitch=67),
                ],
            ),
            "piano_lh": TrackData(
                track_name="piano_lh",
                clef="bass",
                elements=[
                    NoteElement(pitch="C3", duration_quarters=2.0, duration_type="half", midi_pitch=48),
                    NoteElement(pitch="G2", duration_quarters=2.0, duration_type="half", midi_pitch=43),
                ],
            ),
        },
    )

    sys1.measures.append(m1)
    cism.systems.append(sys1)

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        XMLCompiler.compile_score(cism, out_dir)

        # 1. Inspect score.musicxml
        score_path = out_dir / "score.musicxml"
        assert score_path.exists()
        score_content = score_path.read_text(encoding="utf-8")
        assert "<group-symbol>brace</group-symbol>" in score_content

        # Parse with music21 to inspect parts and clefs
        parsed_score = music21.converter.parse(str(score_path))
        # Last two parts are Piano RH (Treble) and Piano LH (Bass)
        rh_part = parsed_score.parts[-2]
        lh_part = parsed_score.parts[-1]

        # Verify clefs
        rh_clefs = [c for c in rh_part.recurse().getElementsByClass(clef.Clef)]
        lh_clefs = [c for c in lh_part.recurse().getElementsByClass(clef.Clef)]
        assert any(isinstance(c, clef.TrebleClef) for c in rh_clefs)
        assert any(isinstance(c, clef.BassClef) for c in lh_clefs)

        # Verify pitch octaves
        rh_pitches = [str(n.pitch) for n in rh_part.recurse().notes]
        lh_pitches = [str(n.pitch) for n in lh_part.recurse().notes]
        assert "E4" in rh_pitches
        assert "G4" in rh_pitches
        assert "C3" in lh_pitches
        assert "G2" in lh_pitches

        # 2. Inspect score_piano.musicxml
        piano_score_path = out_dir / "score_piano.musicxml"
        assert piano_score_path.exists()
        parsed_piano = music21.converter.parse(str(piano_score_path))
        assert len(parsed_piano.parts) == 2
        p_rh = parsed_piano.parts[0]
        p_lh = parsed_piano.parts[1]
        assert any(isinstance(c, clef.TrebleClef) for c in p_rh.recurse().getElementsByClass(clef.Clef))
        assert any(isinstance(c, clef.BassClef) for c in p_lh.recurse().getElementsByClass(clef.Clef))

        # 3. Inspect stems/piano.musicxml
        stem_piano_path = out_dir / "stems" / "piano.musicxml"
        assert stem_piano_path.exists()
        parsed_stem_piano = music21.converter.parse(str(stem_piano_path))
        assert len(parsed_stem_piano.parts) == 2
        stem_rh = parsed_stem_piano.parts[0]
        stem_lh = parsed_stem_piano.parts[1]
        assert any(isinstance(c, clef.TrebleClef) for c in stem_rh.recurse().getElementsByClass(clef.Clef))
        assert any(isinstance(c, clef.BassClef) for c in stem_lh.recurse().getElementsByClass(clef.Clef))


def test_xml_compiler_piano_fallback_split_around_middle_c():
    """Verify that when only a unified 'piano' track exists, XMLCompiler splits elements around Middle C."""
    cism = ScoreCISM(
        score_id="test_piano_split",
        title="Unified Piano Split Test",
        has_piano=True,
    )

    sys1 = SystemData(
        system_index=0,
        page_num=1,
        bounding_box=BoundingBox(x=10, y=10, w=490, h=190),
        staves=[
            StaffInfo(staff_id="s_piano", index=0, role="piano", clef="grand", y_top=50.0, y_bot=150.0),
        ],
    )

    m1 = MeasureData(
        measure_number=1,
        system_index=0,
        time_signature="4/4",
        tempo_bpm=120.0,
        tracks={
            "piano": TrackData(
                track_name="piano",
                clef="grand",
                elements=[
                    # High notes (RH): G4 (MIDI 67), C5 (MIDI 72)
                    NoteElement(pitch="G4", duration_quarters=2.0, duration_type="half", midi_pitch=67),
                    NoteElement(pitch="C5", duration_quarters=2.0, duration_type="half", midi_pitch=72),
                    # Low notes (LH): C3 (MIDI 48), F2 (MIDI 41)
                    NoteElement(pitch="C3", duration_quarters=2.0, duration_type="half", midi_pitch=48),
                    NoteElement(pitch="F2", duration_quarters=2.0, duration_type="half", midi_pitch=41),
                ],
            ),
        },
    )

    sys1.measures.append(m1)
    cism.systems.append(sys1)

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        XMLCompiler.compile_score(cism, out_dir)

        piano_xml = out_dir / "score_piano.musicxml"
        assert piano_xml.exists()
        parsed_piano = music21.converter.parse(str(piano_xml))
        p_rh = parsed_piano.parts[0]
        p_lh = parsed_piano.parts[1]

        rh_pitches = [str(n.pitch) for n in p_rh.recurse().notes]
        lh_pitches = [str(n.pitch) for n in p_lh.recurse().notes]

        assert "G4" in rh_pitches
        assert "C5" in rh_pitches
        assert "C3" in lh_pitches
        assert "F2" in lh_pitches


def test_stitch_movements_parallel_measure_alignment_with_different_printed_numbers():
    """Verify that AudiverisEngine._stitch_movements_bottom_up correctly recombines vocal and piano movements in parallel lockstep without measure displacement."""
    from services.omr_ai_svc.audiveris_engine import AudiverisEngine

    # Page 1: 2 measures (measures 1..2), both vocal and piano complete
    mvt1 = stream.Score()
    p_voc1 = stream.Part(id="Vocal1")
    p_rh1 = stream.Part(id="RH1")
    p_lh1 = stream.Part(id="LH1")
    for i in (1, 2):
        mv = stream.Measure(number=i)
        nv = note.Note("G4", quarterLength=4.0)
        nv.lyric = f"Lyric {i}"
        mv.append(nv)
        p_voc1.append(mv)

        mrh = stream.Measure(number=i)
        mrh.append(note.Note("D5", quarterLength=4.0))
        p_rh1.append(mrh)

        mlh = stream.Measure(number=i)
        mlh.append(note.Note("G3", quarterLength=4.0))
        p_lh1.append(mlh)
    mvt1.append(p_voc1)
    mvt1.append(p_rh1)
    mvt1.append(p_lh1)

    # Page 2: Split into two movements by Audiveris!
    # Movement 2: Vocal only, printed measure numbers 3..4
    mvt2_voc = stream.Score()
    p_voc2 = stream.Part(id="Vocal2")
    for i in (3, 4):
        mv = stream.Measure(number=i)
        nv = note.Note("A4", quarterLength=4.0)
        nv.lyric = f"Lyric {i}"
        mv.append(nv)
        p_voc2.append(mv)
    mvt2_voc.append(p_voc2)

    # Movement 3: Piano only, default 1-based measure numbers (1..2)
    mvt3_pno = stream.Score()
    p_rh2 = stream.Part(id="RH2")
    p_lh2 = stream.Part(id="LH2")
    for i in (1, 2):
        mrh = stream.Measure(number=i)
        mrh.append(note.Note("E5", quarterLength=4.0))
        p_rh2.append(mrh)

        mlh = stream.Measure(number=i)
        mlh.append(note.Note("C3", quarterLength=4.0))
        p_lh2.append(mlh)
    mvt3_pno.append(p_rh2)
    mvt3_pno.append(p_lh2)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir)
        mvt1.write("musicxml", fp=str(tmp_p / "mvt1.mxl"))
        mvt2_voc.write("musicxml", fp=str(tmp_p / "mvt2.mxl"))
        mvt3_pno.write("musicxml", fp=str(tmp_p / "mvt3.mxl"))

        mvt_files = [tmp_p / "mvt1.mxl", tmp_p / "mvt2.mxl", tmp_p / "mvt3.mxl"]
        unified = AudiverisEngine._stitch_movements(
            mvt_files,
            pdf_path=Path("test_score.pdf"),
            layout_data={"has_piano": True},
            score_hints={"accompaniment_type": "piano", "total_measures": 4}
        )

        assert unified is not None
        print("UNIFIED PARTS:", [(p.id, p.partName) for p in unified.parts])
        vocal_part = [p for p in unified.parts if "vocal" in (p.partName or p.id).lower()][0]
        piano_rh = [p for p in unified.parts if "right hand" in (p.partName or "").lower() or "rh" in (p.id or "").lower()][0]
        piano_lh = [p for p in unified.parts if "left hand" in (p.partName or "").lower() or "lh" in (p.id or "").lower()][0]

        # Verify that all parts have exactly measures 1, 2, 3, 4 with notes, not rests!
        v_measures = list(vocal_part.getElementsByClass(stream.Measure))
        rh_measures = list(piano_rh.getElementsByClass(stream.Measure))
        lh_measures = list(piano_lh.getElementsByClass(stream.Measure))

        assert [m.number for m in v_measures] == [1, 2, 3, 4]
        assert [m.number for m in rh_measures] == [1, 2, 3, 4]
        assert [m.number for m in lh_measures] == [1, 2, 3, 4]

        # Verify Measure 3 and 4 have notes for both vocal and piano (not disjointed or rests)
        m3_v_notes = [n for n in v_measures[2].recurse().notes]
        m3_rh_notes = [n for n in rh_measures[2].recurse().notes]
        m3_lh_notes = [n for n in lh_measures[2].recurse().notes]

        assert len(m3_v_notes) == 1 and m3_v_notes[0].pitch.nameWithOctave == "A4"
        assert len(m3_rh_notes) == 1 and m3_rh_notes[0].pitch.nameWithOctave == "E5"
        assert len(m3_lh_notes) == 1 and m3_lh_notes[0].pitch.nameWithOctave == "C3"


def test_router_piano_octave_separation():
    """Verify VoiceRouterEngine cleanly isolates Treble octaves (>= C4) to piano_rh and Bass octaves (< C4) to piano_lh."""
    from services.voice_router_svc.router_engine import VoiceRouterEngine

    cism = ScoreCISM(
        score_id="test_router_octave",
        title="Router Octave Test",
        has_piano=True,
    )
    sys1 = SystemData(
        system_index=0,
        page_num=1,
        bounding_box=BoundingBox(x=0, y=0, w=500, h=200),
        staves=[
            StaffInfo(staff_id="s_rh", index=0, role="piano_rh", clef="treble", y_top=10, y_bot=40),
            StaffInfo(staff_id="s_lh", index=1, role="piano_lh", clef="bass", y_top=60, y_bot=90),
        ],
        measures=[
            MeasureData(
                measure_number=1,
                system_index=0,
                time_signature="4/4",
                quarter_length=4.0,
                raw_staves={
                    # Contaminated with ink bleed: RH has stray G3 (MIDI 55), LH has stray G4 (MIDI 67)
                    "s_rh": TrackData(
                        track_name="s_rh",
                        clef="treble",
                        elements=[
                            NoteElement(pitch="G3", duration_quarters=2.0, duration_type="half", midi_pitch=55),
                            NoteElement(pitch="E5", duration_quarters=2.0, duration_type="half", midi_pitch=76),
                        ],
                    ),
                    "s_lh": TrackData(
                        track_name="s_lh",
                        clef="bass",
                        elements=[
                            NoteElement(pitch="G4", duration_quarters=2.0, duration_type="half", midi_pitch=67),
                            NoteElement(pitch="C3", duration_quarters=2.0, duration_type="half", midi_pitch=48),
                        ],
                    ),
                },
            )
        ]
    )
    cism.systems.append(sys1)

    routed = VoiceRouterEngine.route_score(cism)
    m1_tracks = routed.systems[0].measures[0].tracks

    rh_track = m1_tracks["piano_rh"]
    lh_track = m1_tracks["piano_lh"]

    rh_pitches = [el.pitch for el in rh_track.elements if not el.is_rest]
    lh_pitches = [el.pitch for el in lh_track.elements if not el.is_rest]

    # RH must only have octave >= 4 (E5, G4)
    assert all(MusicTheoryEngine.pitch_to_midi(p) >= 60 for p in rh_pitches)
    assert "E5" in rh_pitches
    assert "G4" in rh_pitches

    # LH must only have octave < 4 (G3, C3)
    assert all(MusicTheoryEngine.pitch_to_midi(p) < 60 for p in lh_pitches)
    assert "G3" in lh_pitches
    assert "C3" in lh_pitches


