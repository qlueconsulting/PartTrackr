from pathlib import Path
import pytest
import music21
from music21 import stream, note, meter

from common.cism_schema import (
    ScoreCISM, SystemData, MeasureData, StaffInfo, TrackData, NoteElement, BoundingBox
)
from services.voice_router_svc.router_engine import VoiceRouterEngine
from services.omr_ai_svc.audiveris_engine import AudiverisEngine


def test_tier1_lyric_anchored_staff_exclusion():
    """
    Tier 1 Test:
    Verify that staves with lyrics or choral indicators are strictly excluded
    from being captured as piano accompaniment, even in 4-staff or 3-staff systems.
    """
    # 4-staff SATB system where all staves have lyrics and vocal labels
    staves = [
        StaffInfo(staff_id="st0", index=0, clef="treble", bracket_type="bracket", role="vocal", y_top=100, y_bot=140, has_lyrics=True, label="Soprano"),
        StaffInfo(staff_id="st1", index=1, clef="treble", bracket_type="bracket", role="vocal", y_top=160, y_bot=200, has_lyrics=True, label="Alto"),
        StaffInfo(staff_id="st2", index=2, clef="bass", bracket_type="bracket", role="vocal", y_top=220, y_bot=260, has_lyrics=True, label="Tenor"),
        StaffInfo(staff_id="st3", index=3, clef="bass", bracket_type="bracket", role="vocal", y_top=280, y_bot=320, has_lyrics=True, label="Bass"),
    ]

    measures = []
    for m_i in range(1, 3):
        raw_staves = {
            "st0": TrackData(track_name="st0", clef="treble", elements=[NoteElement(pitch="G4", duration_quarters=4.0, lyric="Al-")]),
            "st1": TrackData(track_name="st1", clef="treble", elements=[NoteElement(pitch="E4", duration_quarters=4.0, lyric="Al-")]),
            "st2": TrackData(track_name="st2", clef="bass", elements=[NoteElement(pitch="C4", duration_quarters=4.0, lyric="Al-")]),
            "st3": TrackData(track_name="st3", clef="bass", elements=[NoteElement(pitch="C3", duration_quarters=4.0, lyric="Al-")]),
        }
        measures.append(MeasureData(measure_number=m_i, raw_staves=raw_staves))

    sys = SystemData(
        system_index=0,
        page_num=1,
        bounding_box=BoundingBox(x=50, y=100, w=500, h=250),
        staves=staves,
        measures=measures
    )

    cism = ScoreCISM(
        score_id="test_satb_a_cappella",
        title="SATB Test",
        has_piano=True,  # Even if score_hints or preflight erroneously defaulted has_piano=True!
        systems=[sys]
    )

    # Route score
    routed = VoiceRouterEngine.route_score(cism)

    m1_tracks = routed.systems[0].measures[0].tracks

    # Tenor and Bass MUST NOT be captured into Piano!
    # All 4 vocal parts must receive their notes
    assert any(not el.is_rest and el.pitch == "G4" for el in m1_tracks["soprano_1"].elements), "Soprano must have G4"
    assert any(not el.is_rest and el.pitch == "E4" for el in m1_tracks["alto_1"].elements), "Alto must have E4"
    assert any(not el.is_rest and el.pitch == "C4" for el in m1_tracks["tenor_1"].elements), "Tenor must have C4 (NOT stolen by Piano)"
    assert any(not el.is_rest and el.pitch == "C3" for el in m1_tracks["bass_1"].elements), "Bass must have C3 (NOT stolen by Piano)"

    # Piano tracks must be clean rests since all staves had lyrics
    assert all(el.is_rest for el in m1_tracks["piano_rh"].elements), "Piano RH must be rested"
    assert all(el.is_rest for el in m1_tracks["piano_lh"].elements), "Piano LH must be rested"


def test_tier2_piano_intro_vocal_measure_lockstep():
    """
    Tier 2 Test:
    Verify that when the piano plays an intro (measures 1-3) and vocals enter at measure 4,
    vocal measures are NOT shifted forward to measure 1.
    """
    # Create vocal part that only starts at measure 4
    voc_part = stream.Part(id="Vocal")
    for m_num in (4, 5, 6):
        m = stream.Measure(number=m_num)
        n = note.Note("C5", quarterLength=4.0)
        n.lyric = f"Soprano {m_num}"
        m.append(n)
        voc_part.append(m)

    # Extract measures 1, 2, 3, 4, 5, 6 using _extract_measure
    extracted_measures = []
    for target in range(1, 7):
        m_ext = AudiverisEngine._extract_measure(
            part=voc_part,
            m_idx=target - 1,
            target_num=target,
            ts_str="4/4",
            tempo_bpm=120.0,
            bar_ql=4.0
        )
        extracted_measures.append(m_ext)

    # Measures 1, 2, 3 MUST BE RESTS (no notes)
    for idx in (0, 1, 2):
        notes = list(extracted_measures[idx].recurse().notes)
        assert len(notes) == 0, f"Measure {idx + 1} must be a rest during piano intro, but found notes!"

    # Measure 4, 5, 6 MUST HAVE THE NOTES
    for idx in (3, 4, 5):
        m_num = idx + 1
        notes = list(extracted_measures[idx].recurse().notes)
        assert len(notes) == 1, f"Measure {m_num} must have vocal note"
        assert notes[0].pitch.nameWithOctave == "C5"
        assert notes[0].lyric == f"Soprano {m_num}"
