from pathlib import Path
import music21 as m21
import pytest

from app.services.notation import notation_processor, STANDARD_CHORAL_PARTS


def test_standard_choral_parts_taxonomy():
    """Verify standard 11 parts definition."""
    assert len(STANDARD_CHORAL_PARTS) == 11
    assert "Piano" in STANDARD_CHORAL_PARTS
    assert "S1" in STANDARD_CHORAL_PARTS
    assert "S2" in STANDARD_CHORAL_PARTS
    assert "A1" in STANDARD_CHORAL_PARTS
    assert "A2" in STANDARD_CHORAL_PARTS
    assert "T1" in STANDARD_CHORAL_PARTS
    assert "T2" in STANDARD_CHORAL_PARTS
    assert "Bar1" in STANDARD_CHORAL_PARTS
    assert "Bar2" in STANDARD_CHORAL_PARTS
    assert "B1" in STANDARD_CHORAL_PARTS
    assert "B2" in STANDARD_CHORAL_PARTS


def test_satb_piano_extraction(tmp_path):
    """Test standard 4-voice SATB with Piano accompaniment score parsing."""
    score = m21.stream.Score()
    score.metadata = m21.metadata.Metadata()
    score.metadata.title = "Bach Chorale SATB"
    score.metadata.composer = "J.S. Bach"

    for name in ["Soprano", "Alto", "Tenor", "Bass", "Piano"]:
        part = m21.stream.Part()
        part.partName = name
        m = m21.stream.Measure(number=1)
        m.append(m21.note.Note("C4", quarterLength=4))
        part.append(m)
        score.append(part)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems = notation_processor.process_and_extract_stems(score, xml_dir, midi_dir)

    stem_keys = [s.part_key for s in stems]
    assert "Piano" in stem_keys
    assert "S1" in stem_keys
    assert "A1" in stem_keys
    assert "T1" in stem_keys
    assert "B1" in stem_keys

    # Check that MIDI files were generated
    for s in stems:
        assert s.midi_path.exists()
        assert s.note_count >= 1


def test_polyphonic_stem_direction_splitting(tmp_path):
    """Test splitting a shared staff (Women: Soprano + Alto) using stem directions."""
    score = m21.stream.Score()
    part = m21.stream.Part()
    part.partName = "Soprano & Alto"

    m = m21.stream.Measure(number=1)
    # Up stem = Soprano (G4)
    n_up = m21.note.Note("G4", quarterLength=2)
    n_up.stemDirection = "up"
    # Down stem = Alto (E4)
    n_down = m21.note.Note("E4", quarterLength=2)
    n_down.stemDirection = "down"

    m.append(n_up)
    m.append(n_down)
    part.append(m)
    score.append(part)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems = notation_processor.process_and_extract_stems(score, xml_dir, midi_dir)

    stem_keys = [s.part_key for s in stems]
    assert "S1" in stem_keys
    assert "A1" in stem_keys

    s1_stem = next(s for s in stems if s.part_key == "S1")
    a1_stem = next(s for s in stems if s.part_key == "A1")

    # Verify S1 got G4 and A1 got E4
    s1_notes = [n.pitch.nameWithOctave for n in s1_stem.stream.recurse().notes]
    a1_notes = [n.pitch.nameWithOctave for n in a1_stem.stream.recurse().notes]
    assert "G4" in s1_notes
    assert "E4" in a1_notes


def test_choral_divisi_chord_splitting(tmp_path):
    """Test splitting a single choral line into divisi S1 and S2 when chords occur."""
    score = m21.stream.Score()
    part = m21.stream.Part()
    part.partName = "Soprano"

    for i in range(4):
        m = m21.stream.Measure(number=i + 1)
        # 2-note chord (dyad): G4 (lower) and E5 (higher)
        ch = m21.chord.Chord(["G4", "E5"], quarterLength=2)
        m.append(ch)
        part.append(m)
    score.append(part)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems = notation_processor.process_and_extract_stems(score, xml_dir, midi_dir)

    stem_keys = [s.part_key for s in stems]
    assert "S1" in stem_keys
    assert "S2" in stem_keys

    s1_stem = next(s for s in stems if s.part_key == "S1")
    s2_stem = next(s for s in stems if s.part_key == "S2")

    # Higher pitch should go to S1 (E5), lower to S2 (G4)
    s1_pitches = [n.pitch.nameWithOctave for n in s1_stem.stream.recurse().notes]
    s2_pitches = [n.pitch.nameWithOctave for n in s2_stem.stream.recurse().notes]
    assert "E5" in s1_pitches
    assert "G4" in s2_pitches


def test_ssa_aggregation_fallback(tmp_path):
    """Test SSA score maps to Soprano I, Soprano II, and Alto I without failing."""
    score = m21.stream.Score()
    for name in ["Soprano 1", "Soprano 2", "Alto"]:
        part = m21.stream.Part()
        part.partName = name
        m = m21.stream.Measure(number=1)
        m.append(m21.note.Note("A4", quarterLength=4))
        part.append(m)
        score.append(part)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems = notation_processor.process_and_extract_stems(score, xml_dir, midi_dir)

    stem_keys = [s.part_key for s in stems]
    assert "S1" in stem_keys
    assert "S2" in stem_keys
    assert "A1" in stem_keys


def test_ttbb_aggregation_fallback(tmp_path):
    """Test TTBB score maps to Tenor I, Tenor II, Baritone I, and Bass II without failing."""
    score = m21.stream.Score()
    for name in ["Tenor 1", "Tenor 2", "Baritone", "Bass 2"]:
        part = m21.stream.Part()
        part.partName = name
        m = m21.stream.Measure(number=1)
        m.append(m21.note.Note("C3", quarterLength=4))
        part.append(m)
        score.append(part)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems = notation_processor.process_and_extract_stems(score, xml_dir, midi_dir)

    stem_keys = [s.part_key for s in stems]
    assert "T1" in stem_keys
    assert "T2" in stem_keys
    assert "Bar1" in stem_keys
    assert "B2" in stem_keys or "B1" in stem_keys


def test_sab_aggregation_fallback(tmp_path):
    """Test SAB score maps to Soprano I, Alto I, and Baritone I (or Bass I) without failing."""
    score = m21.stream.Score()
    for name in ["Soprano", "Alto", "Baritone"]:
        part = m21.stream.Part()
        part.partName = name
        m = m21.stream.Measure(number=1)
        m.append(m21.note.Note("F4", quarterLength=4))
        part.append(m)
        score.append(part)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems = notation_processor.process_and_extract_stems(score, xml_dir, midi_dir)

    stem_keys = [s.part_key for s in stems]
    assert "S1" in stem_keys
    assert "A1" in stem_keys
    assert "Bar1" in stem_keys or "B1" in stem_keys


def test_unnamed_parts_by_register(tmp_path):
    """Test parts without names infer register from pitch range and clef."""
    score = m21.stream.Score()

    # Part 1: High notes (C5) -> Soprano
    p1 = m21.stream.Part()
    m1 = m21.stream.Measure(number=1)
    m1.append(m21.note.Note("C5", quarterLength=4))
    p1.append(m1)
    score.append(p1)

    # Part 2: Low notes with bass clef (C2) -> Bass
    p2 = m21.stream.Part()
    p2.insert(0, m21.clef.BassClef())
    m2 = m21.stream.Measure(number=1)
    m2.append(m21.note.Note("C2", quarterLength=4))
    p2.append(m2)
    score.append(p2)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems = notation_processor.process_and_extract_stems(score, xml_dir, midi_dir)

    stem_keys = [s.part_key for s in stems]
    assert len(stems) == 11
    assert "S1" in stem_keys
    assert "B1" in stem_keys


def test_all_11_parts_guaranteed_with_bass2_mapping(tmp_path):
    """Verify that when Bass II is missing, it automatically receives notes from Bass I, and all 11 parts exist."""
    score = m21.stream.Score()
    # Score has only Bass 1 and Piano
    bass_part = m21.stream.Part()
    bass_part.partName = "Bass 1"
    m = m21.stream.Measure(number=1)
    m.append(m21.note.Note("D2", quarterLength=4))
    bass_part.append(m)
    score.append(bass_part)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems, analysis = notation_processor.process_and_extract_stems(score, xml_dir, midi_dir, return_analysis=True)

    # All 11 parts must be present
    assert len(stems) == 11
    stem_dict = {s.part_key: s for s in stems}
    for key in ["Piano", "S1", "S2", "A1", "A2", "T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
        assert key in stem_dict

    # Bass II received notes from Bass I
    b1_notes = [n.pitch.nameWithOctave for n in stem_dict["B1"].stream.recurse().notes]
    b2_notes = [n.pitch.nameWithOctave for n in stem_dict["B2"].stream.recurse().notes]
    assert "D2" in b1_notes
    assert "D2" in b2_notes


def test_measure_analysis_and_extended_rests(tmp_path):
    """Test full measure-by-measure analysis, entrances, and extended rests calculation."""
    score = m21.stream.Score()

    # Soprano sings all 6 measures
    sop_part = m21.stream.Part()
    sop_part.partName = "Soprano 1"
    for m_num in range(1, 7):
        m = m21.stream.Measure(number=m_num)
        m.append(m21.note.Note("G4", quarterLength=4))
        sop_part.append(m)
    score.append(sop_part)

    # Tenor sings Measure 1, rests Measures 2-4 (extended rest of 3 bars), enters again at Measure 5
    tenor_part = m21.stream.Part()
    tenor_part.partName = "Tenor 1"
    for m_num in range(1, 7):
        m = m21.stream.Measure(number=m_num)
        if m_num in [1, 5, 6]:
            m.append(m21.note.Note("C4", quarterLength=4))
        else:
            m.append(m21.note.Rest(quarterLength=4))
        tenor_part.append(m)
    score.append(tenor_part)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems, analysis = notation_processor.process_and_extract_stems(score, xml_dir, midi_dir, return_analysis=True)

    assert analysis["total_measures"] == 6
    assert len(analysis["measures"]) == 6

    # Measure 1: both Soprano and Tenor active
    assert "S1" in analysis["measures"][0]["active_parts"]
    assert "T1" in analysis["measures"][0]["active_parts"]

    # Measure 2: Tenor is resting, Soprano is active
    assert "T1" in analysis["measures"][1]["resting_parts"]
    assert "S1" in analysis["measures"][1]["active_parts"]

    # Measure 5: Tenor entrance detected!
    assert "T1" in analysis["measures"][4]["entrances"]

    # Extended rest detected for T1 (Measures 2 to 4)
    t1_rests = analysis["part_extended_rests"]["T1"]
    assert len(t1_rests) >= 1
    rest_span = t1_rests[0]
    assert rest_span["start_measure"] == 2
    assert rest_span["end_measure"] == 4
    assert rest_span["rest_measures"] == 3
    assert rest_span["next_entry_measure"] == 5
    assert rest_span["next_entry_time"] > rest_span["start_time"]


def test_dynamic_time_signature_changes_and_metric_analysis(tmp_path):
    """Test score with multiple time signature changes (4/4 -> 3/4 -> 6/8 -> 2/4)."""
    score = m21.stream.Score()
    sop_part = m21.stream.Part()
    sop_part.partName = "Soprano"

    # M1: 4/4
    m1 = m21.stream.Measure(number=1)
    m1.timeSignature = m21.meter.TimeSignature("4/4")
    m1.append(m21.note.Note("C4", quarterLength=4.0))
    sop_part.append(m1)

    # M2: 3/4
    m2 = m21.stream.Measure(number=2)
    m2.timeSignature = m21.meter.TimeSignature("3/4")
    m2.append(m21.note.Note("D4", quarterLength=3.0))
    sop_part.append(m2)

    # M3: 3/4 (inherited)
    m3 = m21.stream.Measure(number=3)
    m3.append(m21.note.Note("E4", quarterLength=3.0))
    sop_part.append(m3)

    # M4: 6/8
    m4 = m21.stream.Measure(number=4)
    m4.timeSignature = m21.meter.TimeSignature("6/8")
    m4.append(m21.note.Note("F4", quarterLength=3.0))
    sop_part.append(m4)

    # M5: 2/4
    m5 = m21.stream.Measure(number=5)
    m5.timeSignature = m21.meter.TimeSignature("2/4")
    m5.append(m21.note.Note("G4", quarterLength=2.0))
    sop_part.append(m5)

    score.append(sop_part)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems, analysis = notation_processor.process_and_extract_stems(score, xml_dir, midi_dir, return_analysis=True)

    measures = analysis["measures"]
    assert len(measures) == 5

    # Measure 1: 4/4
    assert measures[0]["time_signature"] == "4/4"
    assert measures[0]["numerator"] == 4
    assert measures[0]["denominator"] == 4
    assert measures[0]["beats_per_measure"] == 4
    assert measures[0]["accent_pattern"] == [1200, 680, 920, 680]

    # Measure 2: 3/4
    assert measures[1]["time_signature"] == "3/4"
    assert measures[1]["numerator"] == 3
    assert measures[1]["beats_per_measure"] == 3
    assert measures[1]["accent_pattern"] == [1200, 680, 680]

    # Measure 3: 3/4 (inherited from measure 2)
    assert measures[2]["time_signature"] == "3/4"
    assert measures[2]["beats_per_measure"] == 3

    # Measure 4: 6/8 (compound meter)
    assert measures[3]["time_signature"] == "6/8"
    assert measures[3]["numerator"] == 6
    assert measures[3]["denominator"] == 8
    assert measures[3]["beats_per_measure"] == 6
    assert measures[3]["is_compound"] is True
    assert measures[3]["beat_unit_ql"] == 0.5
    assert measures[3]["accent_pattern"] == [1200, 680, 680, 950, 680, 680]

    # Measure 5: 2/4
    assert measures[4]["time_signature"] == "2/4"
    assert measures[4]["numerator"] == 2
    assert measures[4]["beats_per_measure"] == 2
    assert measures[4]["accent_pattern"] == [1200, 680]

    # Verify time signature milestones were recorded
    ts_milestones = [m["time_signature"] for m in analysis["time_signatures"]]
    assert ts_milestones == ["4/4", "3/4", "6/8", "2/4"]


def test_multimeasure_rest_pdf_consistency(tmp_path):
    """Test that a multi-measure rest expands seamlessly so measure numbers strictly match the PDF."""
    score = m21.stream.Score()
    part = m21.stream.Part()
    part.partName = "Bass"

    # Bar 1: 4/4 active
    m1 = m21.stream.Measure(number=1)
    m1.timeSignature = m21.meter.TimeSignature("4/4")
    m1.append(m21.note.Note("C3", quarterLength=4.0))
    part.append(m1)

    # Bar 2: Multi-measure rest for 4 measures (Bars 2, 3, 4, 5) with ql=16.0
    m2 = m21.stream.Measure(number=2)
    m2.append(m21.note.Rest(quarterLength=16.0))
    part.append(m2)

    # Bar 6: active again!
    m6 = m21.stream.Measure(number=6)
    m6.append(m21.note.Note("E3", quarterLength=4.0))
    part.append(m6)

    score.append(part)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems, analysis = notation_processor.process_and_extract_stems(score, xml_dir, midi_dir, return_analysis=True)

    measures = analysis["measures"]
    # All 6 measures (1, 2, 3, 4, 5, 6) must exist to match the printed PDF markings!
    assert len(measures) == 6
    measure_numbers = [m["number"] for m in measures]
    assert measure_numbers == [1, 2, 3, 4, 5, 6]

    # Ensure start times are monotonically increasing and exact
    for i in range(len(measures) - 1):
        assert measures[i]["end_time"] == pytest.approx(measures[i + 1]["start_time"], abs=0.01)

    # Bars 2, 3, 4, 5 should be resting for Bass
    assert "B1" in measures[0]["active_parts"]
    assert "B1" in measures[1]["resting_parts"]
    assert "B1" in measures[2]["resting_parts"]
    assert "B1" in measures[3]["resting_parts"]
    assert "B1" in measures[4]["resting_parts"]
    assert "B1" in measures[5]["active_parts"]
    assert "B1" in measures[5]["entrances"]


def test_pickup_measure_zero_pdf_numbering(tmp_path):
    """Test pickup (anacrusis) measure 0 retains exact PDF numbering so Measure 1 is first full bar."""
    score = m21.stream.Score()
    part = m21.stream.Part()
    part.partName = "Alto"

    # Pickup bar (Measure 0) with 1 quarter note in 4/4
    m0 = m21.stream.Measure(number=0)
    m0.timeSignature = m21.meter.TimeSignature("4/4")
    m0.append(m21.note.Note("A4", quarterLength=1.0))
    part.append(m0)

    # First full measure (Measure 1)
    m1 = m21.stream.Measure(number=1)
    m1.append(m21.note.Note("B4", quarterLength=4.0))
    part.append(m1)

    score.append(part)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems, analysis = notation_processor.process_and_extract_stems(score, xml_dir, midi_dir, return_analysis=True)

    measures = analysis["measures"]
    assert len(measures) == 2
    assert measures[0]["number"] == 0
    assert "0" in measures[0]["display_number"]
    assert measures[0]["beats_per_measure"] == 1

    assert measures[1]["number"] == 1
    assert measures[1]["display_number"] == "1"
    assert measures[1]["beats_per_measure"] == 4


def test_dynamic_choral_layout_resolver_11_parts(tmp_path):
    """Test dynamic layout resolution (Men unison, Women unison, Interludes, SATB)."""
    score = m21.stream.Score()
    score.metadata = m21.metadata.Metadata()
    score.metadata.title = "The First Nowell"

    p_men = m21.stream.Part(id="TB_Part")
    p_men.partName = "Tenor & Bass"
    p_wom = m21.stream.Part(id="SA_Part")
    p_wom.partName = "Soprano & Alto"
    p_pno = m21.stream.Part(id="Pno")
    p_pno.partName = "Piano"

    for m_num in range(1, 40):
        m_p = m21.stream.Measure(number=m_num)
        m_p.append(m21.note.Note("C4", quarterLength=3.0))
        p_pno.append(m_p)

        m_m = m21.stream.Measure(number=m_num)
        m_w = m21.stream.Measure(number=m_num)

        if 4 <= m_num <= 10:
            m_m.append(m21.note.Note("D3", quarterLength=3.0)) # Men unison in Bass register
        elif 36 <= m_num <= 39:
            m_w.append(m21.note.Note("G4", quarterLength=3.0)) # Women unison in Treble register

        p_men.append(m_m)
        p_wom.append(m_w)

    score.append(p_men)
    score.append(p_wom)
    score.append(p_pno)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems, analysis = notation_processor.process_and_extract_stems(score, xml_dir, midi_dir, return_analysis=True)

    assert len(stems) == 11
    assert "score_profile" in analysis
    assert analysis["score_profile"]["total_measures"] == 112

    # Measure 5 (Men Unison): male parts active, female resting
    m5 = next(m for m in analysis["measures"] if m["number"] == 5)
    for k in ["T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
        assert k in m5["active_parts"]
    for k in ["S1", "S2", "A1", "A2"]:
        assert k in m5["resting_parts"]

    # Measure 33 (Piano interlude): all vocal parts resting
    m33 = next(m for m in analysis["measures"] if m["number"] == 33)
    assert m33["active_parts"] == ["Piano"]
    for k in ["S1", "S2", "A1", "A2", "T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
        assert k in m33["resting_parts"]

    # Measure 37 (Women Unison): female parts active, male resting
    m37 = next(m for m in analysis["measures"] if m["number"] == 37)
    for k in ["S1", "S2", "A1", "A2"]:
        assert k in m37["active_parts"]
    for k in ["T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
        assert k in m37["resting_parts"]


def test_audit_score_components_speed_and_reconciliation(tmp_path):
    """Test audit_score_components verifies staves, recovers dropouts, and runs under 50ms."""
    import time
    score = m21.stream.Score()
    score.metadata = m21.metadata.Metadata()
    score.metadata.title = "The First Nowell"

    p_men = m21.stream.Part()
    p_men.partName = "Men"
    p_pno = m21.stream.Part()
    p_pno.partName = "Piano"

    for m_num in range(1, 20):
        m_m = m21.stream.Measure(number=m_num)
        m_p = m21.stream.Measure(number=m_num)
        if 4 <= m_num <= 10:
            m_m.append(m21.note.Note("D3", quarterLength=3.0))
        # Intentionally introduce accompaniment dropout at m=6..10
        if m_num < 6 or m_num > 10:
            m_p.append(m21.note.Note("C4", quarterLength=3.0))
        p_men.append(m_m)
        p_pno.append(m_p)

    score.append(p_men)
    score.append(p_pno)

    t0 = time.time()
    audit_rep = notation_processor.audit_score_components(score)
    duration_ms = (time.time() - t0) * 1000

    assert duration_ms < 50.0  # Fast in-memory audit (<15ms expected)
    assert "reconciled_match_pct" in audit_rep
    assert "raw_match_pct" in audit_rep
    assert len(audit_rep["measure_grid"]) == 19


def test_keyboard_first_112_measure_lockstep_synchronization(tmp_path):
    """
    Test Keyboard-First extraction and visual-bracket guided voice routing:
    - Master timing anchor extracted from bottom staves (curvy bracket '{') first
    - All 11 rehearsal stems locked to exact 112 measures
    - Every measure padded to exact 3.0 QL (zero duration drift across stems)
    """
    score = m21.stream.Score()
    score.metadata = m21.metadata.Metadata()
    score.metadata.title = "The First Nowell"
    score.metadata.composer = "Mack Wilberg"

    # 4 vocal staves (straight bracket '[')
    for vname in ["Voice1", "Voice2", "Voice3", "Voice4"]:
        p = m21.stream.Part()
        p.id = vname
        p.partName = vname
        for m_num in range(1, 113):
            m = m21.stream.Measure(number=m_num)
            m.quarterLength = 3.0
            if 4 <= m_num <= 28:
                m.append(m21.note.Note("D3", quarterLength=3.0))
            p.append(m)
        score.append(p)

    # 2 piano staves (curvy bracket '{', 'Keyboard')
    for pname in ["P5-Staff1", "P5-Staff2"]:
        p = m21.stream.Part()
        p.id = pname
        p.partName = "Piano"
        for m_num in range(1, 113):
            m = m21.stream.Measure(number=m_num)
            m.quarterLength = 3.0
            m.append(m21.chord.Chord(["C3", "G3", "C4"], quarterLength=3.0))
            p.append(m)
        score.append(p)

    xml_dir = tmp_path / "xml"
    midi_dir = tmp_path / "midi"
    stems, analysis = notation_processor.process_and_extract_stems(
        score, xml_dir, midi_dir, return_analysis=True, fallback_title="The First Nowell"
    )

    assert len(stems) == 11
    assert analysis["total_measures"] == 112
    assert len(analysis["measures"]) == 112

    # Verify every single stem has exact same duration and measure count
    expected_duration = stems[0].duration_seconds
    for st in stems:
        assert st.measure_count == 112
        assert abs(st.duration_seconds - expected_duration) < 0.05
        assert st.midi_path.exists()
        assert st.xml_path.exists()




