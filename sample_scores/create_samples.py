import os
from pathlib import Path
import music21 as m21

SAMPLE_DIR = Path(__file__).resolve().parent


def generate_satb_piano_xml() -> Path:
    """
    Generates a rich multi-measure SATB + Piano Accompaniment choral score
    for testing and rehearsal demonstration.
    """
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    out_file = SAMPLE_DIR / "bach_satb_piano.musicxml"

    score = m21.stream.Score()
    score.metadata = m21.metadata.Metadata()
    score.metadata.title = "O Sacred Head Now Wounded"
    score.metadata.composer = "J.S. Bach"

    tempo = m21.tempo.MetronomeMark(number=80)
    time_sig = m21.meter.TimeSignature("4/4")
    key_sig = m21.key.KeySignature(1)  # G major / E minor (1 sharp)

    # 1. Soprano (Soprano I)
    sop_part = m21.stream.Part()
    sop_part.partName = "Soprano I"
    sop_part.id = "S1"
    sop_part.insert(0, m21.clef.TrebleClef())
    sop_part.insert(0, time_sig)
    sop_part.insert(0, key_sig)
    sop_part.insert(0, tempo)

    # 2. Alto (Alto I)
    alto_part = m21.stream.Part()
    alto_part.partName = "Alto I"
    alto_part.id = "A1"
    alto_part.insert(0, m21.clef.TrebleClef())
    alto_part.insert(0, time_sig)
    alto_part.insert(0, key_sig)

    # 3. Tenor (Tenor I)
    tenor_part = m21.stream.Part()
    tenor_part.partName = "Tenor I"
    tenor_part.id = "T1"
    tenor_part.insert(0, m21.clef.Treble8vbClef())
    tenor_part.insert(0, time_sig)
    tenor_part.insert(0, key_sig)

    # 4. Bass (Bass I)
    bass_part = m21.stream.Part()
    bass_part.partName = "Bass I"
    bass_part.id = "B1"
    bass_part.insert(0, m21.clef.BassClef())
    bass_part.insert(0, time_sig)
    bass_part.insert(0, key_sig)

    # 5. Piano Accompaniment (Piano Score)
    piano_part = m21.stream.Part()
    piano_part.partName = "Piano Score"
    piano_part.id = "Piano"
    piano_part.insert(0, m21.instrument.Piano())
    piano_part.insert(0, m21.clef.TrebleClef())
    piano_part.insert(0, time_sig)
    piano_part.insert(0, key_sig)

    # Harmonic Progression: Em - B7 - Em - C - G - D - Em
    # Measures 1 - 4
    # Measure 1: Em -> B7
    # Measure 2: Em -> C
    # Measure 3: G -> D
    # Measure 4: Em (Cadence)

    sop_notes = [
        # M1
        [("E4", 1.0), ("G4", 1.0), ("F#4", 1.0), ("E4", 1.0)],
        # M2
        [("G4", 1.0), ("A4", 1.0), ("B4", 2.0)],
        # M3
        [("B4", 1.0), ("A4", 1.0), ("G4", 1.0), ("F#4", 1.0)],
        # M4
        [("E4", 4.0)],
    ]

    alto_notes = [
        # M1
        [("B3", 1.0), ("E4", 1.0), ("D#4", 1.0), ("B3", 1.0)],
        # M2
        [("E4", 1.0), ("E4", 1.0), ("D4", 2.0)],
        # M3
        [("D4", 1.0), ("D4", 1.0), ("B3", 1.0), ("D4", 1.0)],
        # M4
        [("B3", 4.0)],
    ]

    tenor_notes = [
        # M1
        [("G3", 1.0), ("B3", 1.0), ("B3", 1.0), ("G3", 1.0)],
        # M2
        [("B3", 1.0), ("C4", 1.0), ("F#3", 2.0)],
        # M3
        [("G3", 1.0), ("F#3", 1.0), ("E3", 1.0), ("A3", 1.0)],
        # M4
        [("G3", 4.0)],
    ]

    bass_notes = [
        # M1
        [("E3", 1.0), ("E3", 1.0), ("B2", 1.0), ("E3", 1.0)],
        # M2
        [("E3", 1.0), ("A2", 1.0), ("B2", 2.0)],
        # M3
        [("G2", 1.0), ("D3", 1.0), ("E3", 1.0), ("D3", 1.0)],
        # M4
        [("E2", 4.0)],
    ]

    piano_chords = [
        # M1: Em, Em, B7, Em
        [(["E3", "G3", "B3", "E4"], 1.0), (["E3", "G3", "B3", "E4"], 1.0), (["B2", "D#3", "F#3", "A3"], 1.0), (["E3", "G3", "B3"], 1.0)],
        # M2: Em, Am, B7
        [(["E3", "G3", "B3"], 1.0), (["C3", "E3", "A3", "C4"], 1.0), (["B2", "D#3", "F#3", "B3"], 2.0)],
        # M3: G, D, Em, B7
        [(["G2", "B2", "D3", "G3"], 1.0), (["D3", "F#3", "A3", "D4"], 1.0), (["E3", "G3", "B3"], 1.0), (["D3", "F#3", "A3"], 1.0)],
        # M4: Em
        [(["E2", "B2", "E3", "G3", "B3", "E4"], 4.0)],
    ]

    for m_idx in range(4):
        # Soprano
        m_s = m21.stream.Measure(number=m_idx + 1)
        for pitch_str, dur in sop_notes[m_idx]:
            n = m21.note.Note(pitch_str, quarterLength=dur)
            n.stemDirection = "up"
            m_s.append(n)
        sop_part.append(m_s)

        # Alto
        m_a = m21.stream.Measure(number=m_idx + 1)
        for pitch_str, dur in alto_notes[m_idx]:
            n = m21.note.Note(pitch_str, quarterLength=dur)
            n.stemDirection = "down"
            m_a.append(n)
        alto_part.append(m_a)

        # Tenor
        m_t = m21.stream.Measure(number=m_idx + 1)
        for pitch_str, dur in tenor_notes[m_idx]:
            n = m21.note.Note(pitch_str, quarterLength=dur)
            n.stemDirection = "up"
            m_t.append(n)
        tenor_part.append(m_t)

        # Bass
        m_b = m21.stream.Measure(number=m_idx + 1)
        for pitch_str, dur in bass_notes[m_idx]:
            n = m21.note.Note(pitch_str, quarterLength=dur)
            n.stemDirection = "down"
            m_b.append(n)
        bass_part.append(m_b)

        # Piano
        m_p = m21.stream.Measure(number=m_idx + 1)
        for chord_pitches, dur in piano_chords[m_idx]:
            c = m21.chord.Chord(chord_pitches, quarterLength=dur)
            m_p.append(c)
        piano_part.append(m_p)

    score.append(sop_part)
    score.append(alto_part)
    score.append(tenor_part)
    score.append(bass_part)
    score.append(piano_part)

    score.write("musicxml", fp=str(out_file))
    print(f"Sample SATB + Piano score created at: {out_file}")
    return out_file


if __name__ == "__main__":
    generate_satb_piano_xml()
