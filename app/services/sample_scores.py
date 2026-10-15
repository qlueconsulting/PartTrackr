from pathlib import Path
from music21 import stream, note, chord, meter, tempo, clef, layout, metadata

def create_sample_satb_with_piano(output_path: Path):
    """
    Creates an authentic SATB Choral Anthem with Piano Accompaniment:
    - Measures 1-2: Piano Intro (Solo Keyboard under brace, voices rest)
    - Measures 3-4: Women Choir entrance (Soprano & Alto, Men rest)
    - Measures 5-6: Full SATB Choir with divisi chords
    - Measure 7: Piano Interlude (Voices rest)
    - Measure 8: Full Choir + Piano Grand Coda
    """
    s = stream.Score()
    s.metadata = metadata.Metadata()
    s.metadata.title = "Choral Anthem of Hope"
    s.metadata.composer = "A. Antigravity"

    # 4 Vocal parts
    sop = stream.Part(id="Soprano")
    sop.partName = "Soprano"
    sop.partAbbreviation = "S."

    alt = stream.Part(id="Alto")
    alt.partName = "Alto"
    alt.partAbbreviation = "A."

    ten = stream.Part(id="Tenor")
    ten.partName = "Tenor"
    ten.partAbbreviation = "T."

    bas = stream.Part(id="Bass")
    bas.partName = "Bass"
    bas.partAbbreviation = "B."

    # Piano parts (Treble and Bass staves)
    pno_rh = stream.Part(id="Piano_RH")
    pno_rh.partName = "Piano"
    pno_rh.partAbbreviation = "Pno."

    pno_lh = stream.Part(id="Piano_LH")
    pno_lh.partName = "Piano (LH)"
    pno_lh.partAbbreviation = "Pno. LH"

    # Staff groups: Bracket for voices, Brace for Piano
    vocal_group = layout.StaffGroup([sop, alt, ten, bas], symbol="bracket", name="Chorus")
    piano_group = layout.StaffGroup([pno_rh, pno_lh], symbol="brace", name="Piano")

    s.append(vocal_group)
    s.append(piano_group)

    # 8 Measures in 4/4, tempo 108
    for m_num in range(1, 9):
        # Create measures
        m_sop = stream.Measure(number=m_num)
        m_alt = stream.Measure(number=m_num)
        m_ten = stream.Measure(number=m_num)
        m_bas = stream.Measure(number=m_num)
        m_prh = stream.Measure(number=m_num)
        m_plh = stream.Measure(number=m_num)

        for m in [m_sop, m_alt, m_ten, m_bas, m_prh, m_plh]:
            m.timeSignature = meter.TimeSignature("4/4")
            if m_num == 1:
                m.insert(0, tempo.MetronomeMark(number=108.0))

        # Clefs
        if m_num == 1:
            m_sop.insert(0, clef.TrebleClef())
            m_alt.insert(0, clef.TrebleClef())
            m_ten.insert(0, clef.Treble8vbClef())
            m_bas.insert(0, clef.BassClef())
            m_prh.insert(0, clef.TrebleClef())
            m_plh.insert(0, clef.BassClef())

        # Piano Accompaniment (written in all measures)
        # LH Arpeggio / bass line
        m_plh.append(note.Note("C3", quarterLength=1.0))
        m_plh.append(note.Note("G3", quarterLength=1.0))
        m_plh.append(note.Note("E3", quarterLength=1.0))
        m_plh.append(note.Note("G3", quarterLength=1.0))

        # RH Harmony chords
        m_prh.append(chord.Chord(["C4", "E4", "G4"], quarterLength=2.0))
        m_prh.append(chord.Chord(["E4", "G4", "C5"], quarterLength=2.0))

        # Vocal Lines by section
        if m_num in [1, 2, 7]:
            # M1-2: Intro; M7: Interlude -> All voices rest!
            m_sop.append(note.Rest(quarterLength=4.0))
            m_alt.append(note.Rest(quarterLength=4.0))
            m_ten.append(note.Rest(quarterLength=4.0))
            m_bas.append(note.Rest(quarterLength=4.0))

        elif m_num in [3, 4]:
            # M3-4: Women only (Treble), Men rest
            # Soprano with divisi chord
            m_sop.append(chord.Chord(["G4", "B4"], quarterLength=2.0))
            m_sop.append(chord.Chord(["A4", "C5"], quarterLength=2.0))
            # Alto
            m_alt.append(note.Note("E4", quarterLength=2.0))
            m_alt.append(note.Note("F4", quarterLength=2.0))
            # Men rest
            m_ten.append(note.Rest(quarterLength=4.0))
            m_bas.append(note.Rest(quarterLength=4.0))

        elif m_num in [5, 6]:
            # M5-6: Full SATB with Divisi in Soprano and Bass
            m_sop.append(chord.Chord(["C5", "E5"], quarterLength=2.0))
            m_sop.append(chord.Chord(["D5", "F5"], quarterLength=2.0))

            m_alt.append(note.Note("G4", quarterLength=2.0))
            m_alt.append(note.Note("A4", quarterLength=2.0))

            m_ten.append(note.Note("E4", quarterLength=2.0))
            m_ten.append(note.Note("F4", quarterLength=2.0))

            # Bass with Baritone/Bass divisi chord
            m_bas.append(chord.Chord(["C3", "G3"], quarterLength=2.0))
            m_bas.append(chord.Chord(["D3", "A3"], quarterLength=2.0))

        elif m_num == 8:
            # M8: Coda
            m_sop.append(chord.Chord(["E5", "G5"], quarterLength=4.0))
            m_alt.append(note.Note("C5", quarterLength=4.0))
            m_ten.append(note.Note("G4", quarterLength=4.0))
            m_bas.append(chord.Chord(["C3", "C4"], quarterLength=4.0))

        sop.append(m_sop)
        alt.append(m_alt)
        ten.append(m_ten)
        bas.append(m_bas)
        pno_rh.append(m_prh)
        pno_lh.append(m_plh)

    s.append(sop)
    s.append(alt)
    s.append(ten)
    s.append(bas)
    s.append(pno_rh)
    s.append(pno_lh)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    s.write("musicxml", fp=str(output_path))
    return s

def create_sample_unison_choral(output_path: Path):
    """
    Creates a score showcasing Dynamic Choral Voice Routing:
    - Measures 1-2: Women's Unison (Treble G-Clef) -> routes to S1, S2, A1, A2. Men rest.
    - Measures 3-4: Men's Unison (Bass F-Clef) -> routes to T1, T2, Bar1, Bar2, B1, B2. Women rest.
    - Measures 5-6: 2-staff SATB (Staff 1 Treble SA, Staff 2 Bass TB).
    """
    s = stream.Score()
    s.metadata = metadata.Metadata()
    s.metadata.title = "Unison and Divisi Choral Study"
    s.metadata.composer = "Choral Dynamics Lab"

    # 2 Staves (SA and TB) + Piano
    sa_part = stream.Part(id="SA_Part")
    sa_part.partName = "Soprano & Alto"

    tb_part = stream.Part(id="TB_Part")
    tb_part.partName = "Tenor & Bass"

    pno_part = stream.Part(id="Piano")
    pno_part.partName = "Piano"

    for m_num in range(1, 7):
        m_sa = stream.Measure(number=m_num)
        m_tb = stream.Measure(number=m_num)
        m_pno = stream.Measure(number=m_num)

        for m in [m_sa, m_tb, m_pno]:
            m.timeSignature = meter.TimeSignature("3/4")
            if m_num == 1:
                m.insert(0, tempo.MetronomeMark(number=96.0))

        if m_num == 1:
            m_sa.insert(0, clef.TrebleClef())
            m_tb.insert(0, clef.BassClef())
            m_pno.insert(0, clef.TrebleClef())

        # Piano
        m_pno.append(chord.Chord(["D4", "F#4", "A4"], quarterLength=3.0))

        if m_num in [1, 2]:
            # Women's Unison
            m_sa.append(note.Note("A4", quarterLength=1.0))
            m_sa.append(note.Note("B4", quarterLength=1.0))
            m_sa.append(note.Note("C#5", quarterLength=1.0))
            m_tb.append(note.Rest(quarterLength=3.0))
        elif m_num in [3, 4]:
            # Men's Unison
            m_sa.append(note.Rest(quarterLength=3.0))
            m_tb.append(note.Note("D3", quarterLength=1.0))
            m_tb.append(note.Note("E3", quarterLength=1.0))
            m_tb.append(note.Note("F#3", quarterLength=1.0))
        else:
            # Polyphony SA & TB
            m_sa.append(chord.Chord(["F#4", "D5"], quarterLength=3.0))
            m_tb.append(chord.Chord(["D3", "A3"], quarterLength=3.0))

        sa_part.append(m_sa)
        tb_part.append(m_tb)
        pno_part.append(m_pno)

    s.append(sa_part)
    s.append(tb_part)
    s.append(pno_part)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    s.write("musicxml", fp=str(output_path))
    return s
