from pathlib import Path
import pytest
import music21
from music21 import stream, note, chord, meter, clef, layout, expressions

from app.services.sample_scores import create_sample_unison_choral, create_sample_satb_with_piano
from app.services.notation_processor import NotationProcessor

def test_unison_voice_routing(tmp_path: Path):
    """
    Rule A2:
    - Single Treble Clef under straight bracket (Women's unison): S1, S2, A1, A2 active; Men rest.
    - Single Bass Clef under straight bracket (Men's unison): T1, T2, Bar1, Bar2, B1, B2 active; Female rest.
    """
    score_path = tmp_path / "unison.musicxml"
    create_sample_unison_choral(score_path)
    
    proc = NotationProcessor(score_path)
    stems, analysis = proc.extract_all_stems()
    
    # M1 is Women's unison
    m1_active = analysis[0]["active_parts"]
    assert "Piano" in m1_active
    for f in ["S1", "S2", "A1", "A2"]:
        assert f in m1_active, f"Female part {f} expected active in Women's Unison"
    for m in ["T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
        assert m not in m1_active, f"Male part {m} should be resting in Women's Unison"

    # M3 is Men's unison
    m3_active = analysis[2]["active_parts"]
    assert "Piano" in m3_active
    for m in ["T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
        assert m in m3_active, f"Male part {m} expected active in Men's Unison"
    for f in ["S1", "S2", "A1", "A2"]:
        assert f not in m3_active, f"Female part {f} should be resting in Men's Unison"

def test_interlude_cleanliness_suppression(tmp_path: Path):
    """
    Rule A2: When only the curvy bracket { (Keyboard) is active, all 10 vocal parts rest.
    Suppress any OMR voice bleed during interludes.
    """
    score_path = tmp_path / "anthem.musicxml"
    create_sample_satb_with_piano(score_path)
    
    proc = NotationProcessor(score_path)
    stems, analysis = proc.extract_all_stems()
    
    # M1 and M2 are Piano Intro; M7 is Piano Interlude
    for m_num in [1, 2, 7]:
        m_data = analysis[m_num - 1]
        assert m_data["active_parts"] == ["Piano"], (
            f"Measure {m_num} should only have Piano active, got: {m_data['active_parts']}"
        )
        # Verify all 10 vocal parts contain strictly whole rests
        for key in ["S1", "S2", "A1", "A2", "T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
            m_stem = stems[key].parts[0].measure(m_num)
            assert len(m_stem.flatten().notes) == 0, f"Voice bleed detected in stem {key} during M{m_num} interlude"

def test_divisi_chord_separation(tmp_path: Path):
    """
    Rule A2: When polyphonic voices or divisi chords appear on a single staff,
    separate upper stems/pitches to Voice 1 (S1/T1) and lower to Voice 2 (S2/A2/B2).
    """
    s = stream.Score()
    p = stream.Part(id="Soprano")
    p.partName = "Soprano"
    
    m1 = stream.Measure(number=1)
    m1.timeSignature = meter.TimeSignature("4/4")
    # Divisi chord: C5 (lower) and G5 (upper)
    m1.append(chord.Chord(["C5", "G5"], quarterLength=4.0))
    p.append(m1)
    s.append(p)
    
    score_path = tmp_path / "divisi.musicxml"
    s.write("musicxml", fp=str(score_path))
    
    proc = NotationProcessor(score_path)
    stems, _ = proc.extract_all_stems()
    
    s1_m1 = stems["S1"].parts[0].measure(1)
    s2_m1 = stems["S2"].parts[0].measure(1)
    
    s1_note = s1_m1.flatten().notes.first()
    s2_note = s2_m1.flatten().notes.first()
    
    assert s1_note.pitch.nameWithOctave == "G5", "S1 should receive higher pitch G5"
    assert s2_note.pitch.nameWithOctave == "C5", "S2 should receive lower pitch C5"
