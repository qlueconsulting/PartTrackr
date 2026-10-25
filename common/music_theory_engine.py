import logging
import re
from fractions import Fraction
from typing import Dict, List, Tuple, Optional, Any

from common.cism_schema import NoteElement

logger = logging.getLogger("common.music_theory")


class MusicTheoryEngine:
    """
    Music Theory, Grammar, and Symbolic Notation Solver for Choral OMR:
    1. Key signature Circle-of-Fifths resolution & measure accidental propagation.
    2. Clef octave transposition (e.g. Treble 8vb for Tenors).
    3. Metric beat-grid quantization and proportional rhythm solving.
    4. Tie vs. Slur disambiguation.
    5. Vocal range verification and voice-leading outlier filtering.
    """

    SHARP_ORDER = ["F", "C", "G", "D", "A", "E", "B"]
    FLAT_ORDER = ["B", "E", "A", "D", "G", "C", "F"]

    NOTE_BASE_SEMITONES = {
        "C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11
    }

    VOCAL_RANGES = {
        "soprano": (57, 84),   # A3 to C6
        "alto": (52, 77),      # E3 to F5
        "tenor": (45, 72),     # A2 to C5
        "bass": (36, 65),      # C2 to F4
        "vocal_men": (36, 72), # C2 to C5
        "vocal": (45, 84),     # Generic vocal
        "piano_rh": (48, 108), # C3 to C8
        "piano_lh": (24, 72),  # C1 to C5
    }

    @classmethod
    def diatonic_step_to_step_and_octave(cls, step_val: int, clef: str = "treble") -> Tuple[str, int]:
        """
        Analytically converts staff vertical step_val (where 0 = bottom staff line, 8 = top staff line)
        to standard diatonic step letter ('C', 'D', 'E', 'F', 'G', 'A', 'B') and octave integer.
        Handles arbitrary ledger lines above and below without clipping or defaulting.
        """
        diatonic = ["C", "D", "E", "F", "G", "A", "B"]
        is_bass = clef in ("bass", "f") or clef.startswith("bass")
        base_diatonic_idx = 18 if is_bass else 30
        idx = base_diatonic_idx + int(step_val)
        step = diatonic[idx % 7]
        octave = idx // 7
        return step, octave

    @classmethod
    def resolve_key_alterations(cls, fifths: int) -> Dict[str, str]:
        """
        Returns map of diatonic step -> accidental string based on Circle of Fifths.
        e.g. fifths=+2 (D Major) -> {'F': '#', 'C': '#'}
             fifths=+4 (E Major) -> {'F': '#', 'C': '#', 'G': '#', 'D': '#'}
             fifths=-2 (Bb Major) -> {'B': 'b', 'E': 'b'}
        """
        alterations: Dict[str, str] = {}
        if fifths > 0:
            for i in range(min(7, fifths)):
                alterations[cls.SHARP_ORDER[i]] = "#"
        elif fifths < 0:
            for i in range(min(7, abs(fifths))):
                alterations[cls.FLAT_ORDER[i]] = "b"
        return alterations

    @classmethod
    def pitch_to_midi(cls, pitch_str: str) -> int:
        """Converts scientific pitch e.g. 'F#4', 'Bb3', 'C4' to standard MIDI number."""
        m = re.match(r"^([A-Ga-g])([#b]?)(-?\d+)$", pitch_str.strip())
        if not m:
            return 60
        step, acc, oct_str = m.groups()
        step = step.upper()
        octave = int(oct_str)
        semitone = cls.NOTE_BASE_SEMITONES.get(step, 0)
        if acc == "#":
            semitone += 1
        elif acc == "b":
            semitone -= 1
        return (octave + 1) * 12 + semitone

    @classmethod
    def midi_to_pitch(cls, midi_num: int, preferred_accidental: str = "#") -> str:
        """Converts standard MIDI number (0-127) to scientific pitch notation."""
        midi_num = max(0, min(127, int(midi_num)))
        octave = (midi_num // 12) - 1
        pitch_class = midi_num % 12
        if preferred_accidental == "b":
            names = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
        else:
            names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        return f"{names[pitch_class]}{octave}"

    @classmethod
    def resolve_step_to_pitch(
        cls,
        step: str,
        octave: int,
        key_fifths: int = 0,
        explicit_accidental: Optional[str] = None,
        measure_accidentals: Optional[Dict[Tuple[str, int], str]] = None,
        clef: str = "treble"
    ) -> Tuple[str, int]:
        """
        Calculates exact pitch string and MIDI number given a diatonic step,
        key signature, in-measure accidentals, and clef.
        """
        step = step.upper()
        # 1. Check explicit accidental first
        acc = explicit_accidental
        if acc:
            if acc in ("natural", "n"):
                acc = ""
            if measure_accidentals is not None:
                measure_accidentals[(step, octave)] = acc
        elif measure_accidentals is not None and (step, octave) in measure_accidentals:
            # 2. Check active in-measure accidental from previous note in same bar
            acc = measure_accidentals[(step, octave)]
        else:
            # 3. Check key signature alterations
            key_alts = cls.resolve_key_alterations(key_fifths)
            acc = key_alts.get(step, "")

        pitch_str = f"{step}{acc}{octave}"
        midi_pitch = cls.pitch_to_midi(pitch_str)

        # 4. Clef transposition: Treble 8vb sounds 1 octave lower
        if clef in ("treble_8vb", "tenor_octave"):
            midi_pitch -= 12
            pitch_str = cls.midi_to_pitch(midi_pitch, preferred_accidental="#" if key_fifths >= 0 else "b")

        return pitch_str, midi_pitch

    @classmethod
    def classify_arc(cls, pitch_a: Optional[str], pitch_b: Optional[str]) -> str:
        """Determines if a curved line between notes is a Tie (same pitch) or Slur (melisma)."""
        if not pitch_a or not pitch_b:
            return "slur"
        return "tie" if pitch_a == pitch_b else "slur"

    @classmethod
    def is_in_range(cls, midi_pitch: int, role: str) -> bool:
        """Validates that a pitch falls within the realistic acoustic range of the voice part."""
        bounds = cls.VOCAL_RANGES.get(role, (36, 84))
        return bounds[0] <= midi_pitch <= bounds[1]

    @classmethod
    def solve_measure_rhythm(
        cls,
        elements: List[NoteElement],
        bar_quarter_length: float = 4.0,
        time_signature: str = "4/4"
    ) -> List[NoteElement]:
        """
        Solves note offsets and durations using proportional spacing and metric beat-grid quantization.
        Enforces exact conservation: sum(durations) == bar_quarter_length.
        """
        if not elements:
            dur_type = "whole" if bar_quarter_length >= 4.0 else ("dotted_half" if bar_quarter_length >= 3.0 else "half")
            return [NoteElement(pitch=None, duration_quarters=bar_quarter_length, duration_type=dur_type, offset_quarters=0.0, is_rest=True)]

        # If already single full rest, return sanitized
        if len(elements) == 1 and elements[0].is_rest:
            dur_type = "whole" if bar_quarter_length >= 4.0 else ("dotted_half" if bar_quarter_length >= 3.0 else "half")
            return [NoteElement(pitch=None, duration_quarters=bar_quarter_length, duration_type=dur_type, offset_quarters=0.0, is_rest=True)]

        # Quantize offsets to 0.25 beat (16th note) or 0.5 beat (8th note)
        grid_step = 0.5 if "8" in time_signature else 0.25
        sorted_elems = sorted(elements, key=lambda e: e.offset_quarters)

        result: List[NoteElement] = []
        cur_time = 0.0

        for el in sorted_elems:
            raw_off = el.offset_quarters
            # Snap offset to grid
            snapped_off = round(raw_off / grid_step) * grid_step
            snapped_off = max(cur_time, min(bar_quarter_length - 0.25, snapped_off))

            if snapped_off > cur_time:
                # Insert rest gap
                gap = snapped_off - cur_time
                dur_type = "quarter" if abs(gap - 1.0) < 0.1 else ("half" if abs(gap - 2.0) < 0.1 else "eighth")
                result.append(NoteElement(
                    pitch=None,
                    duration_quarters=gap,
                    duration_type=dur_type,
                    offset_quarters=cur_time,
                    is_rest=True
                ))
                cur_time = snapped_off

            raw_dur = el.duration_quarters
            snapped_dur = max(0.25, min(bar_quarter_length - cur_time, round(raw_dur / grid_step) * grid_step))
            dur_t = "quarter" if abs(snapped_dur - 1.0) < 0.1 else ("half" if abs(snapped_dur - 2.0) < 0.1 else ("dotted_half" if abs(snapped_dur - 3.0) < 0.1 else "eighth"))

            el_out = el.model_copy()
            el_out.offset_quarters = cur_time
            el_out.duration_quarters = snapped_dur
            el_out.duration_type = dur_t
            result.append(el_out)
            cur_time += snapped_dur

            if cur_time >= bar_quarter_length:
                break

        if cur_time < bar_quarter_length:
            tail = bar_quarter_length - cur_time
            dur_type = "quarter" if abs(tail - 1.0) < 0.1 else ("half" if abs(tail - 2.0) < 0.1 else "eighth")
            result.append(NoteElement(
                pitch=None,
                duration_quarters=tail,
                duration_type=dur_type,
                offset_quarters=cur_time,
                is_rest=True
            ))

        return result
