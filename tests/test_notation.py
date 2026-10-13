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

