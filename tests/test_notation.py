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
    assert len(stems) == 2
    assert "S1" in stem_keys
    assert "B1" in stem_keys
