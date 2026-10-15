from pathlib import Path
import pytest
import music21

from app.services.sample_scores import create_sample_satb_with_piano
from app.services.notation_processor import NotationProcessor, STEM_TAXONOMY

def test_extract_all_11_stems(tmp_path: Path):
    score_file = tmp_path / "anthem.musicxml"
    orig_score = create_sample_satb_with_piano(score_file)
    
    proc = NotationProcessor(score_file)
    stems, analysis = proc.extract_all_stems()
    
    # 1. Exactly 11 standardized stems
    assert len(stems) == 11
    for key in STEM_TAXONOMY:
        assert key in stems
        assert len(stems[key].parts) == 1
        assert stems[key].parts[0].id == key

    # 2. Accompaniment is foundational timing anchor
    # Original score has 8 measures
    assert len(analysis) == 8
    for key in STEM_TAXONOMY:
        m_count = len(stems[key].parts[0].getElementsByClass(music21.stream.Measure))
        assert m_count == 8, f"Stem {key} does not have exactly 8 measures (got {m_count})"

def test_piano_ground_truth_no_hallucination(tmp_path: Path):
    """
    Rule A5: DO NOT invent, fabricate, or hallucinate notes or chords for the piano
    that are not written in the score. Accompaniment must match printed notes exactly.
    """
    score_file = tmp_path / "anthem.musicxml"
    orig_score = create_sample_satb_with_piano(score_file)
    
    proc = NotationProcessor(score_file)
    stems, _ = proc.extract_all_stems()
    
    piano_stem = stems["Piano"]
    
    # Collect all pitches from piano stem
    extracted_pitches = set()
    for n in piano_stem.flatten().notes:
        if isinstance(n, music21.chord.Chord):
            for p in n.pitches:
                extracted_pitches.add(p.nameWithOctave)
        else:
            extracted_pitches.add(n.pitch.nameWithOctave)
            
    # Check that every extracted pitch in the piano stem is an authentic printed pitch
    # from the original score's piano parts
    orig_piano_pitches = set()
    for p in proc.accomp_parts:
        for n in p.flatten().notes:
            if isinstance(n, music21.chord.Chord):
                for pit in n.pitches:
                    orig_piano_pitches.add(pit.nameWithOctave)
            else:
                orig_piano_pitches.add(n.pitch.nameWithOctave)
                
    assert extracted_pitches == orig_piano_pitches
    assert len(extracted_pitches) > 0

def test_zero_measure_drift(tmp_path: Path):
    score_file = tmp_path / "anthem.musicxml"
    create_sample_satb_with_piano(score_file)
    
    proc = NotationProcessor(score_file)
    stems, analysis = proc.extract_all_stems()
    
    # Verify every measure in every stem has identical quarterLength
    for i, a in enumerate(analysis):
        expected_ql = a["quarter_length"]
        for key in STEM_TAXONOMY:
            m = stems[key].parts[0].measure(a["measure_number"])
            assert m is not None
            assert float(m.duration.quarterLength) == expected_ql, (
                f"Stem {key} measure {a['measure_number']} length is {m.duration.quarterLength}, expected {expected_ql}"
            )
