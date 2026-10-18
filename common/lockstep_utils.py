from fractions import Fraction
from typing import List, Tuple, Dict, Any
from common.cism_schema import NoteElement, TrackData


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
