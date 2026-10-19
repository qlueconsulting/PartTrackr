from fractions import Fraction
from typing import List, Tuple, Dict, Any, Optional
from common.cism_schema import (
    NoteElement,
    TrackData,
    ScoreCISM,
    SystemData,
    MeasureData,
    StaffInfo,
    BoundingBox,
)
from common.taxonomy import CANONICAL_11_PARTS, PART_METADATA


def calculate_bar_quarter_length(time_signature: str) -> Fraction:
    """Parses time signatures like '4/4', '3/4', '6/8', '12/8' to exact Fraction quarterLength."""
    parts = time_signature.strip().split("/")
    if len(parts) == 2:
        try:
            num = int(parts[0])
            den = int(parts[1])
            # In music21 / standard notation: quarter note = 1.0 quarterLength.
            # den = 4 means quarter note -> num * 1
            # den = 8 means eighth note -> num * 0.5 = num * (4 / 8)
            return Fraction(num * 4, den)
        except Exception:
            pass
    return Fraction(4, 1)


def clamp_and_pad_track_elements(
    elements: List[NoteElement],
    bar_quarter_length: Fraction
) -> List[NoteElement]:
    """
    Enforces Rule B: Metric Lockstep Synchronization & Duration Clamping.
    - Clamps overflowing notes past the printed time signature duration.
    - Pads underflowing gaps and measure tails with rests.
    - Preserves exact bar quarterLength down to zero drift.
    """
    if not elements:
        # Full measure rest
        return [
            NoteElement(
                pitch=None,
                duration_quarters=float(bar_quarter_length),
                duration_type="whole" if bar_quarter_length >= 4 else "half",
                offset_quarters=0.0,
                is_rest=True
            )
        ]

    # Sort elements by offset
    sorted_elems = sorted(elements, key=lambda el: el.offset_quarters)

    valid_elems: List[Tuple[Fraction, Fraction, NoteElement]] = []
    for el in sorted_elems:
        off = Fraction(f"{el.offset_quarters:.4f}")
        dur = Fraction(f"{el.duration_quarters:.4f}")

        if off >= bar_quarter_length:
            # Starts beyond bar end, omit OMR bleed
            continue
        elif off + dur > bar_quarter_length:
            # Clamped note
            clamped_dur = bar_quarter_length - off
            el_copy = el.model_copy()
            el_copy.duration_quarters = float(clamped_dur)
            valid_elems.append((off, clamped_dur, el_copy))
        else:
            valid_elems.append((off, dur, el))

    if not valid_elems:
        return [
            NoteElement(
                pitch=None,
                duration_quarters=float(bar_quarter_length),
                duration_type="whole" if bar_quarter_length >= 4 else "half",
                offset_quarters=0.0,
                is_rest=True
            )
        ]

    sanitized: List[NoteElement] = []
    current_pos = Fraction(0)

    for off, dur, el in valid_elems:
        if off > current_pos:
            # Underflow gap before element -> pad with rest
            gap_dur = off - current_pos
            sanitized.append(
                NoteElement(
                    pitch=None,
                    duration_quarters=float(gap_dur),
                    duration_type="quarter" if gap_dur >= 1 else "eighth",
                    offset_quarters=float(current_pos),
                    is_rest=True
                )
            )
        sanitized.append(el)
        current_pos = max(current_pos, off + dur)

    if current_pos < bar_quarter_length:
        # Tail padding with rest
        tail_dur = bar_quarter_length - current_pos
        sanitized.append(
            NoteElement(
                pitch=None,
                duration_quarters=float(tail_dur),
                duration_type="quarter" if tail_dur >= 1 else "eighth",
                offset_quarters=float(current_pos),
                is_rest=True
            )
        )

    return sanitized


def reconcile_cism_measures(
    cism: ScoreCISM,
    target_total_measures: Optional[int],
    target_time_signature: Optional[str] = None,
    target_tempo_bpm: Optional[float] = None,
    has_piano: Optional[bool] = None,
) -> ScoreCISM:
    """
    Enforces the user's verified total_measures as hard ground truth across the entire pipeline.
    - If extracted count > target: Truncates trailing phantom/empty measures past target_total_measures.
    - If extracted count < target: Synthesizes missing measures up to target_total_measures with rests in lockstep.
    - Re-indexes measure numbering sequentially (1..target_total_measures).
    - Locks time_signature and tempo_bpm if provided in user hints.
    """
    if has_piano is not None:
        cism.has_piano = has_piano

    all_meas = cism.all_measures()
    last_ts = target_time_signature or (all_meas[-1].time_signature if all_meas else "4/4") or "4/4"
    last_bpm = target_tempo_bpm or (all_meas[-1].tempo_bpm if all_meas else 120.0) or 120.0
    bar_ql = float(calculate_bar_quarter_length(last_ts))

    if not target_total_measures or target_total_measures <= 0:
        cism.total_measures = len(all_meas)
        for m in all_meas:
            if target_time_signature:
                m.time_signature = target_time_signature
                m.quarter_length = bar_ql
            if target_tempo_bpm:
                m.tempo_bpm = target_tempo_bpm
        return cism

    current_count = len(all_meas)

    # 1. Truncate overflow measures
    if current_count > target_total_measures:
        measures_kept = 0
        new_systems: List[SystemData] = []
        for sys in cism.systems:
            if measures_kept >= target_total_measures:
                break
            remaining_needed = target_total_measures - measures_kept
            if len(sys.measures) <= remaining_needed:
                measures_kept += len(sys.measures)
                new_systems.append(sys)
            else:
                sys.measures = sys.measures[:remaining_needed]
                measures_kept += remaining_needed
                new_systems.append(sys)
                break
        cism.systems = new_systems
        cism.total_systems = len(cism.systems)

    # 2. Pad underflow measures
    elif current_count < target_total_measures:
        if not cism.systems:
            cism.systems.append(
                SystemData(
                    system_index=0,
                    page_num=1,
                    bounding_box=BoundingBox(x=0.0, y=0.0, w=612.0, h=792.0),
                    staves=[],
                    measures=[]
                )
            )
            cism.total_systems = 1

        last_sys = cism.systems[-1]
        needed = target_total_measures - current_count

        for idx in range(needed):
            m_num = current_count + idx + 1
            # Canonical 11-part tracks
            tracks: Dict[str, TrackData] = {}
            for p in CANONICAL_11_PARTS:
                clef_name = PART_METADATA.get(p, {}).get("default_clef", "treble")
                tracks[p] = TrackData(
                    track_name=p,
                    clef=clef_name,
                    elements=[
                        NoteElement(
                            pitch=None,
                            duration_quarters=bar_ql,
                            duration_type="whole" if bar_ql >= 4.0 else "half",
                            offset_quarters=0.0,
                            is_rest=True
                        )
                    ]
                )

            # Raw staves if system staves exist
            raw_staves: Dict[str, TrackData] = {}
            for st in last_sys.staves:
                raw_staves[st.staff_id] = TrackData(
                    track_name=st.staff_id,
                    clef=st.clef,
                    elements=[
                        NoteElement(
                            pitch=None,
                            duration_quarters=bar_ql,
                            duration_type="whole" if bar_ql >= 4.0 else "half",
                            offset_quarters=0.0,
                            is_rest=True
                        )
                    ]
                )

            new_m = MeasureData(
                measure_number=m_num,
                time_signature=last_ts,
                tempo_bpm=last_bpm,
                quarter_length=bar_ql,
                tracks=tracks,
                raw_staves=raw_staves
            )
            last_sys.measures.append(new_m)

    # 3. Renumber all measures sequentially 1..target_total_measures & apply overrides
    seq = 1
    for sys in cism.systems:
        for m in sys.measures:
            m.measure_number = seq
            if target_time_signature:
                m.time_signature = target_time_signature
                m.quarter_length = bar_ql
            if target_tempo_bpm:
                m.tempo_bpm = target_tempo_bpm
            seq += 1

    cism.total_measures = target_total_measures
    return cism
