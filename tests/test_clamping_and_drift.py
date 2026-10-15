from fractions import Fraction
from pathlib import Path
import pytest
import music21
from music21 import stream, note, meter, tempo

from app.services.notation_processor import NotationProcessor, STEM_TAXONOMY

def test_overflow_bar_boundary_clamping(tmp_path: Path):
    """
    Test that notes overflowing past the measure boundary (e.g. half note placed on beat 3 in 3/4 time)
    are strictly clamped so the measure quarterLength == 3.0 QL and subsequent measures remain locked.
    """
    s = stream.Score()
    p = stream.Part(id="Vocal")
    p.partName = "Soprano"
    
    # Measure 1: 3/4 time, beat 1 (1.0), beat 2 (1.0), beat 3 half note (2.0) -> spills past bar (total 4.0 QL)
    m1 = stream.Measure(number=1)
    m1.timeSignature = meter.TimeSignature("3/4")
    m1.append(tempo.MetronomeMark(number=120.0))
    m1.append(note.Note("C4", quarterLength=1.0))
    m1.append(note.Note("D4", quarterLength=1.0))
    m1.append(note.Note("E4", quarterLength=2.0)) # Overflowing note!
    
    # Measure 2: normal 3/4 measure
    m2 = stream.Measure(number=2)
    m2.timeSignature = meter.TimeSignature("3/4")
    m2.append(note.Note("F4", quarterLength=3.0))
    
    p.append(m1)
    p.append(m2)
    s.append(p)
    
    test_score_path = tmp_path / "clamping_overflow.musicxml"
    s.write("musicxml", fp=str(test_score_path))
    
    proc = NotationProcessor(test_score_path)
    stems, analysis = proc.extract_all_stems()
    
    assert len(analysis) == 2
    for key in STEM_TAXONOMY:
        stem_p = stems[key].parts[0]
        # Measure 1 must be clamped strictly to 3.0 QL
        res_m1 = stem_p.measure(1)
        assert float(res_m1.duration.quarterLength) == 3.0, f"Stem {key} M1 not clamped to 3.0 QL"
        
        # Measure 2 must be strictly 3.0 QL
        res_m2 = stem_p.measure(2)
        assert float(res_m2.duration.quarterLength) == 3.0, f"Stem {key} M2 not 3.0 QL"

def test_underflow_padding(tmp_path: Path):
    """
    Test that measures underfilled (e.g. only 1 quarter note in 4/4 time)
    are padded with rests up to 4.0 QL.
    """
    s = stream.Score()
    p = stream.Part(id="Piano")
    p.partName = "Piano"
    
    m1 = stream.Measure(number=1)
    m1.timeSignature = meter.TimeSignature("4/4")
    m1.append(note.Note("C4", quarterLength=1.0)) # Only 1 beat in 4/4 measure!
    
    p.append(m1)
    s.append(p)
    
    test_score_path = tmp_path / "padding_underflow.musicxml"
    s.write("musicxml", fp=str(test_score_path))
    
    proc = NotationProcessor(test_score_path)
    stems, analysis = proc.extract_all_stems()
    
    for key in STEM_TAXONOMY:
        res_m = stems[key].parts[0].measure(1)
        assert float(res_m.duration.quarterLength) == 4.0

def test_tuplet_fraction_safety(tmp_path: Path):
    """
    Test that native Fraction tuplet durations (e.g. triplet quarter notes = 2/3 QL)
    export valid MusicXML and MIDI without 'inexpressible duration' exceptions.
    """
    s = stream.Score()
    p = stream.Part(id="Soprano")
    p.partName = "Soprano"
    
    m1 = stream.Measure(number=1)
    m1.timeSignature = meter.TimeSignature("2/4") # 2.0 QL
    
    # Triplet quarter notes (3 notes of 2/3 QL = 2.0 QL)
    for i in range(3):
        n = note.Note("G4")
        n.duration = music21.duration.Duration(Fraction(2, 3))
        m1.insert(float(i * Fraction(2, 3)), n)
        
    p.append(m1)
    s.append(p)
    
    test_score_path = tmp_path / "triplets.musicxml"
    s.write("musicxml", fp=str(test_score_path))
    
    proc = NotationProcessor(test_score_path)
    stems, analysis = proc.extract_all_stems()
    
    # Verify export to MusicXML and MIDI without exception
    for key in STEM_TAXONOMY:
        sc = stems[key]
        mxml_out = tmp_path / f"{key}_tuplet.musicxml"
        mid_out = tmp_path / f"{key}_tuplet.mid"
        sc.write("musicxml", fp=str(mxml_out))
        sc.write("midi", fp=str(mid_out))
        assert mxml_out.exists()
        assert mid_out.exists()
