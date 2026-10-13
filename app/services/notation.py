import copy
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import music21 as m21

logger = logging.getLogger("parttrackr.notation")

STANDARD_CHORAL_PARTS = {
    "Piano": "Piano Score",
    "S1": "Soprano I",
    "S2": "Soprano II",
    "A1": "Alto I",
    "A2": "Alto II",
    "T1": "Tenor I",
    "T2": "Tenor II",
    "Bar1": "Baritone I",
    "Bar2": "Baritone II",
    "B1": "Bass I",
    "B2": "Bass II",
}

ALL_CHORAL_KEYS = [
    "Piano",
    "S1",
    "S2",
    "A1",
    "A2",
    "T1",
    "T2",
    "Bar1",
    "Bar2",
    "B1",
    "B2",
]

# Preferred General MIDI instrument mappings for clear rehearsal playback
GM_INSTRUMENTS = {
    "Piano": m21.instrument.Piano(),             # GM 0 - Acoustic Grand Piano
    "S1": m21.instrument.Choir(),                # GM 52 - Choir Aahs
    "S2": m21.instrument.Choir(),
    "A1": m21.instrument.Choir(),
    "A2": m21.instrument.Choir(),
    "T1": m21.instrument.Choir(),
    "T2": m21.instrument.Choir(),
    "Bar1": m21.instrument.Choir(),
    "Bar2": m21.instrument.Choir(),
    "B1": m21.instrument.Choir(),
    "B2": m21.instrument.Choir(),
}


@dataclass
class ExtractedStem:
    part_key: str              # e.g. "S1", "A1", "T1", "B1", "Piano"
    part_name: str             # e.g. "Soprano I", "Piano Score"
    is_accompaniment: bool
    original_part_name: str
    stream: m21.stream.Part
    xml_path: Optional[Path] = None
    midi_path: Optional[Path] = None
    duration_seconds: float = 0.0
    pitch_range: Optional[str] = None
    measure_count: int = 0
    note_count: int = 0


class NotationProcessor:
    """
    Processes MusicXML scores, performs measure-by-measure structure analysis,
    and guarantees all 11 standard choral rehearsal parts are always available.
    """

    def __init__(self):
        self.last_measure_analysis: Dict[str, Any] = {}

    def parse_score(self, file_path: Path) -> m21.stream.Score:
        """Parse MusicXML, MXL, or MIDI score using music21."""
        file_path = Path(file_path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Score file does not exist: {file_path}")

        logger.info("Parsing score file with music21: %s", file_path)
        try:
            score = m21.converter.parse(str(file_path))
            if not isinstance(score, m21.stream.Score):
                wrapped = m21.stream.Score()
                if isinstance(score, m21.stream.Part):
                    wrapped.append(score)
                else:
                    for el in score:
                        wrapped.append(el)
                score = wrapped
            return score
        except Exception as exc:
            logger.error("Failed to parse score %s: %s", file_path, exc)
            raise ValueError(f"Failed to parse music notation file: {exc}")

    def extract_metadata(self, score: m21.stream.Score, fallback_title: str) -> Tuple[str, Optional[str]]:
        """Extract title and composer from score metadata."""
        title = fallback_title
        composer = None
        if score.metadata:
            if score.metadata.title:
                title = score.metadata.title
            elif score.metadata.movementName:
                title = score.metadata.movementName
            if score.metadata.composer:
                composer = score.metadata.composer

        title = re.sub(r"\.[^.]+$", "", title).strip() or fallback_title
        return title, composer

    def _get_part_search_string(self, part: m21.stream.Part) -> str:
        """Extract clean text representation of part name and instruments."""
        tokens = []
        if part.partName:
            tokens.append(str(part.partName))
        if part.partAbbreviation:
            tokens.append(str(part.partAbbreviation))
        if not tokens and part.id and not str(part.id).isdigit():
            tokens.append(str(part.id))

        for inst in part.getInstruments():
            if inst.instrumentName:
                tokens.append(str(inst.instrumentName))
            if inst.instrumentAbbreviation:
                tokens.append(str(inst.instrumentAbbreviation))

        return " ".join(tokens).lower()

    def is_accompaniment_part(self, part: m21.stream.Part) -> bool:
        """Determine if a part is piano or instrumental accompaniment."""
        name_str = self._get_part_search_string(part)
        keywords = [
            "piano", "pno", "klavier", "organ", "org", "accomp", "acc.", "acc",
            "keyboard", "cembalo", "harpsichord", "reduction", "continuo", "orch"
        ]
        return any(kw in name_str for kw in keywords)

    def identify_part_category(self, part: m21.stream.Part) -> str:
        """
        Classifies a part into raw categories:
        'piano', 'soprano', 'alto', 'tenor', 'baritone', 'bass',
        'soprano_alto', 'tenor_bass', 's1', 's2', 'a1', 'a2', 't1', 't2', 'bar1', 'bar2', 'b1', 'b2',
        or 'unknown'.
        """
        if self.is_accompaniment_part(part):
            return "piano"

        name_str = self._get_part_search_string(part)

        if any(term in name_str for term in ["soprano & alto", "soprano/alto", "s/a", "sa", "women", "treble 1 & 2"]):
            return "soprano_alto"
        if any(term in name_str for term in ["tenor & bass", "tenor/bass", "t/b", "tb", "men"]):
            return "tenor_bass"

        if re.search(r"\bsoprano\s*(1|i)\b|\bs\s*1\b|\bdescant\b", name_str):
            return "s1"
        if re.search(r"\bsoprano\s*(2|ii)\b|\bs\s*2\b|\bmezzo\b", name_str):
            return "s2"
        if re.search(r"\bsoprano\b|\bsopr\b|\bcantus\b|\btreble\b", name_str):
            return "soprano"

        if re.search(r"\balto\s*(1|i)\b|\ba\s*1\b|\bcontralto\s*(1|i)\b", name_str):
            return "a1"
        if re.search(r"\balto\s*(2|ii)\b|\ba\s*2\b|\bcontralto\s*(2|ii)\b", name_str):
            return "a2"
        if re.search(r"\balto\b|\baltus\b|\bcontralto\b", name_str):
            return "alto"

        if re.search(r"\btenor\s*(1|i)\b|\bt\s*1\b", name_str):
            return "t1"
        if re.search(r"\btenor\s*(2|ii)\b|\bt\s*2\b", name_str):
            return "t2"
        if re.search(r"\btenor\b", name_str):
            return "tenor"

        if re.search(r"\bbaritone\s*(1|i)\b|\bbar\s*1\b", name_str):
            return "bar1"
        if re.search(r"\bbaritone\s*(2|ii)\b|\bbar\s*2\b", name_str):
            return "bar2"
        if re.search(r"\bbaritone\b|\bbar\b", name_str):
            return "baritone"

        if re.search(r"\bbass\s*(1|i)\b|\bb\s*1\b|\bbasso\s*(1|i)\b", name_str):
            return "b1"
        if re.search(r"\bbass\s*(2|ii)\b|\bb\s*2\b|\bbasso\s*(2|ii)\b", name_str):
            return "b2"
        if re.search(r"\bbass\b|\bbasso\b", name_str):
            return "bass"

        return "unknown"

    def split_polyphonic_staff(
        self, part: m21.stream.Part, upper_label: str, lower_label: str
    ) -> Tuple[m21.stream.Part, m21.stream.Part]:
        """
        Splits a shared choral staff into two parts by analyzing voices, stem directions, and chord dyads.
        """
        upper_part = m21.stream.Part()
        upper_part.partName = upper_label
        upper_part.id = f"{upper_label.replace(' ', '_')}"

        lower_part = m21.stream.Part()
        lower_part.partName = lower_label
        lower_part.id = f"{lower_label.replace(' ', '_')}"

        measures = part.getElementsByClass(m21.stream.Measure)
        if not measures:
            return copy.deepcopy(part), copy.deepcopy(part)

        for m in measures:
            up_m = m21.stream.Measure(number=m.number)
            low_m = m21.stream.Measure(number=m.number)

            for header_el in m.getElementsByClass([m21.meter.TimeSignature, m21.key.KeySignature, m21.clef.Clef]):
                up_m.append(copy.deepcopy(header_el))
                low_m.append(copy.deepcopy(header_el))

            voices = m.voices
            if len(voices) >= 2:
                for el in voices[0]:
                    if isinstance(el, (m21.note.Note, m21.chord.Chord, m21.note.Rest)):
                        up_m.append(copy.deepcopy(el))
                for el in voices[1]:
                    if isinstance(el, (m21.note.Note, m21.chord.Chord, m21.note.Rest)):
                        low_m.append(copy.deepcopy(el))
            else:
                notes_and_chords = m.getElementsByClass([m21.note.Note, m21.chord.Chord, m21.note.Rest])
                for el in notes_and_chords:
                    if isinstance(el, m21.note.Rest):
                        up_m.append(copy.deepcopy(el))
                        low_m.append(copy.deepcopy(el))
                    elif isinstance(el, m21.chord.Chord):
                        pitches = sorted(el.pitches)
                        if len(pitches) >= 2:
                            up_n = m21.note.Note(pitches[-1], quarterLength=el.quarterLength)
                            up_n.offset = el.offset
                            up_m.append(up_n)
                            low_n = m21.note.Note(pitches[0], quarterLength=el.quarterLength)
                            low_n.offset = el.offset
                            low_m.append(low_n)
                        else:
                            up_m.append(copy.deepcopy(el))
                            low_m.append(copy.deepcopy(el))
                    elif isinstance(el, m21.note.Note):
                        if el.stemDirection == "up":
                            up_m.append(copy.deepcopy(el))
                        elif el.stemDirection == "down":
                            low_m.append(copy.deepcopy(el))
                        else:
                            up_m.append(copy.deepcopy(el))
                            low_m.append(copy.deepcopy(el))

            upper_part.append(up_m)
            lower_part.append(low_m)

        return upper_part, lower_part

    def check_for_divisi_chords(self, part: m21.stream.Part) -> bool:
        """Check if a staff has significant chord divisi (more than 15% chords)."""
        notes = list(part.recurse().getElementsByClass([m21.note.Note, m21.chord.Chord]))
        if not notes:
            return False
        chord_count = sum(1 for n in notes if isinstance(n, m21.chord.Chord))
        return (chord_count / len(notes)) >= 0.15

    def split_choral_divisi(
        self, part: m21.stream.Part, part_name_1: str, part_name_2: str
    ) -> Tuple[m21.stream.Part, m21.stream.Part]:
        """Split a part into divisi 1 and 2 when chords or multiple voices occur."""
        return self.split_polyphonic_staff(part, part_name_1, part_name_2)

    def guess_register_from_notes(self, part: m21.stream.Part) -> str:
        """Guess vocal register from average pitch and clef."""
        pitches = [n.pitch.midi for n in part.recurse().notes if hasattr(n, "pitch")]
        if not pitches:
            clefs = list(part.recurse().getElementsByClass(m21.clef.Clef))
            if clefs and isinstance(clefs[0], m21.clef.BassClef):
                return "bass"
            return "soprano"

        avg_pitch = sum(pitches) / len(pitches)
        if avg_pitch >= 68:      # ~G#4 and above
            return "soprano"
        elif avg_pitch >= 60:    # ~C4 to G4
            return "alto"
        elif avg_pitch >= 52:    # ~E3 to B3
            return "tenor"
        elif avg_pitch >= 45:    # ~A2 to D#3
            return "baritone"
        else:
            return "bass"

    def combine_piano_staves(self, parts: List[m21.stream.Part]) -> m21.stream.Part:
        """Combine multiple accompaniment parts into a single Piano Score part."""
        if len(parts) == 1:
            res = copy.deepcopy(parts[0])
            res.partName = "Piano Score"
            res.id = "Piano"
            return res

        combined = m21.stream.Part()
        combined.partName = "Piano Score"
        combined.id = "Piano"

        measure_nums = set()
        for p in parts:
            for m in p.getElementsByClass(m21.stream.Measure):
                measure_nums.add(m.number)

        for m_num in sorted(measure_nums):
            new_m = m21.stream.Measure(number=m_num)
            for p in parts:
                p_m = p.measure(m_num)
                if p_m:
                    for header_el in p_m.getElementsByClass([m21.meter.TimeSignature, m21.key.KeySignature, m21.clef.Clef]):
                        new_m.insert(float(header_el.offset), copy.deepcopy(header_el))
                    break
            seen = set()
            for p in parts:
                p_m = p.measure(m_num)
                if p_m:
                    for el in p_m:
                        if not isinstance(el, (m21.meter.TimeSignature, m21.key.KeySignature, m21.clef.Clef)):
                            p_key = (float(el.offset), tuple(getattr(el, 'pitches', [])) if hasattr(el, 'pitches') else None)
                            if p_key not in seen:
                                seen.add(p_key)
                                new_m.insert(float(el.offset), copy.deepcopy(el))
            if not list(new_m.notes):
                first_pm = parts[0].measure(m_num)
                rest_ql = float(first_pm.quarterLength) if first_pm else 4.0
                new_m.insert(0.0, m21.note.Rest(quarterLength=rest_ql))
            combined.append(new_m)

        return combined

    def create_choral_reduction_piano(self, vocal_parts: List[m21.stream.Part]) -> m21.stream.Part:
        """
        Creates a rehearsal piano reduction by aggregating notes from vocal parts.
        Allows singers of a cappella scores to rehearse with piano accompaniment.
        """
        reduction = m21.stream.Part()
        reduction.partName = "Piano Score (Rehearsal Reduction)"
        reduction.id = "Piano"

        if not vocal_parts:
            return reduction

        measure_nums = set()
        for vp in vocal_parts:
            for m in vp.getElementsByClass(m21.stream.Measure):
                measure_nums.add(m.number)

        for m_num in sorted(measure_nums):
            new_m = m21.stream.Measure(number=m_num)
            first_p_m = vocal_parts[0].measure(m_num)
            if first_p_m:
                for h in first_p_m.getElementsByClass([m21.meter.TimeSignature, m21.key.KeySignature, m21.clef.Clef]):
                    new_m.insert(float(h.offset), copy.deepcopy(h))
            seen = set()
            for vp in vocal_parts:
                vp_m = vp.measure(m_num)
                if vp_m:
                    for el in vp_m.notes:
                        p_key = (float(el.offset), tuple(getattr(el, 'pitches', [])))
                        if p_key not in seen:
                            seen.add(p_key)
                            new_m.insert(float(el.offset), copy.deepcopy(el))
            if not list(new_m.notes):
                rest_ql = float(first_p_m.quarterLength) if first_p_m else 4.0
                new_m.insert(0.0, m21.note.Rest(quarterLength=rest_ql))
            reduction.append(new_m)

        return reduction

    def compute_time_signature_meta(
        self, ts: m21.meter.TimeSignature, bpm: float, ql: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculates detailed metric and acoustic properties for a given TimeSignature:
        - Exact beats per measure count
        - Beat unit quarter length & duration in seconds at current BPM
        - Frequency accent pattern for downbeat, secondary accents, and regular beats
        """
        num = int(ts.numerator)
        den = int(ts.denominator)
        is_compound = (num in [6, 9, 12] and den == 8)

        if is_compound:
            # Compound meters (6/8, 9/8, 12/8): rehearsal pulse counts eighth notes
            beats = num
            unit_ql = 0.5
            accents = []
            for b in range(num):
                if b == 0:
                    accents.append(1200)  # Downbeat (high crisp tone)
                elif b % 3 == 0:
                    accents.append(950)   # Secondary accent (e.g. beat 4 in 6/8, beats 4 & 7 in 9/8)
                else:
                    accents.append(680)   # Off-beat ticks
        else:
            beats = num
            unit_ql = 4.0 / den
            accents = []
            for b in range(num):
                if b == 0:
                    accents.append(1200)  # Downbeat
                elif num == 4 and b == 2:
                    accents.append(920)   # Beat 3 in 4/4
                elif num == 5 and b in [2, 3]:
                    accents.append(920)   # Secondary pulse in 5/4
                else:
                    accents.append(680)   # Regular beat ticks

        # If this is an anacrusis / pickup measure with less quarterLength than a standard bar
        standard_bar_ql = float(ts.barDuration.quarterLength)
        if ql is not None and ql < standard_bar_ql - 0.05:
            pickup_beats = max(1, round(ql / unit_ql))
            beats = pickup_beats
            accents = accents[:pickup_beats]

        beat_dur = (unit_ql / (bpm / 60.0)) if bpm > 0 else (unit_ql * 0.6)

        return {
            "time_signature": f"{num}/{den}",
            "numerator": num,
            "denominator": den,
            "beats_per_measure": beats,
            "beat_unit_ql": round(unit_ql, 4),
            "beat_duration": round(beat_dur, 4),
            "is_compound": is_compound,
            "accent_pattern": accents,
        }

    def analyze_measures(
        self,
        score: m21.stream.Score,
        reconciled_streams: Dict[str, m21.stream.Part],
        master_tempo_bpm: float = 100.0,
    ) -> Dict[str, Any]:
        """
        Full measure-by-measure analysis of the score:
        - Music-sensitive to dynamic time signature changes across measures (altering measure counts,
          note lengths, and metronome tone accent patterns).
        - Strictly consistent with printed PDF measure markings (preserving pickup bar 0, suffixes,
          and interpolating multi-measure rests so seeking lands on the exact printed bar).
        - Part activity (which parts have notes in each measure).
        - Part entrances (measures where a part enters after resting).
        - Extended rest segments for each part with precomputed jump-to entrance timestamps.
        """
        # 1. Collect all tempo changes
        tempo_points: List[Tuple[float, float]] = []
        for el in score.recurse().getElementsByClass(m21.tempo.MetronomeMark):
            if el.number:
                tempo_points.append((float(el.offset), float(el.number)))
        tempo_points.sort(key=lambda x: x[0])
        if not tempo_points or tempo_points[0][0] > 0:
            tempo_points.insert(0, (0.0, master_tempo_bpm))

        def offset_to_seconds(offset: float) -> float:
            total_sec = 0.0
            cur_bpm = tempo_points[0][1]
            last_off = 0.0
            for tp_off, tp_bpm in tempo_points:
                if offset <= tp_off:
                    break
                total_sec += (tp_off - last_off) * (60.0 / cur_bpm)
                last_off = tp_off
                cur_bpm = tp_bpm
            total_sec += (offset - last_off) * (60.0 / cur_bpm)
            return round(total_sec, 3)

        def get_bpm_at_offset(offset: float) -> float:
            cur_bpm = tempo_points[0][1]
            for tp_off, tp_bpm in tempo_points:
                if offset >= tp_off:
                    cur_bpm = tp_bpm
                else:
                    break
            return cur_bpm

        # 2. Collect all TimeSignature changes across the entire score
        score_ts_list: List[Tuple[float, m21.meter.TimeSignature]] = []
        for el in score.recurse().getElementsByClass(m21.meter.TimeSignature):
            score_ts_list.append((float(el.offset), el))
        for p in reconciled_streams.values():
            for m in p.getElementsByClass(m21.stream.Measure):
                if m.timeSignature:
                    score_ts_list.append((float(m.offset), m.timeSignature))
        score_ts_list.sort(key=lambda x: x[0])

        default_ts = score_ts_list[0][1] if score_ts_list else m21.meter.TimeSignature("4/4")
        if not score_ts_list or score_ts_list[0][0] > 0:
            score_ts_list.insert(0, (0.0, default_ts))

        def get_ts_at_offset(off: float) -> m21.meter.TimeSignature:
            active_ts = score_ts_list[0][1]
            for ts_off, ts_obj in score_ts_list:
                if ts_off <= off + 0.001:
                    active_ts = ts_obj
                else:
                    break
            return active_ts

        # 3. Collect all raw measures across all reconciled parts by offset
        raw_measures_by_offset: Dict[float, Dict[str, Any]] = {}
        for key, part in reconciled_streams.items():
            for m in part.getElementsByClass(m21.stream.Measure):
                off = float(m.offset)
                ql = float(m.quarterLength)
                num = m.number
                suffix = getattr(m, "numberSuffix", "") or ""
                if off not in raw_measures_by_offset:
                    raw_measures_by_offset[off] = {
                        "offset": off,
                        "quarterLength": ql,
                        "number": num,
                        "suffix": suffix,
                        "parts_present": {key: m},
                    }
                else:
                    raw_measures_by_offset[off]["parts_present"][key] = m
                    if 0 < ql < raw_measures_by_offset[off]["quarterLength"]:
                        raw_measures_by_offset[off]["quarterLength"] = ql
                    if raw_measures_by_offset[off]["number"] is None and num is not None:
                        raw_measures_by_offset[off]["number"] = num
                        raw_measures_by_offset[off]["suffix"] = suffix

        sorted_offsets = sorted(raw_measures_by_offset.keys())
        if not sorted_offsets:
            sorted_offsets = [0.0]
            raw_measures_by_offset[0.0] = {
                "offset": 0.0,
                "quarterLength": 4.0,
                "number": 1,
                "suffix": "",
                "parts_present": {},
            }

        # 4. Expand measures with strict PDF consistency & dynamic time signature tracking
        measures_list = []
        meter_changes = []
        last_recorded_ts_str = None

        for i, off in enumerate(sorted_offsets):
            data = raw_measures_by_offset[off]
            ts = get_ts_at_offset(off)
            standard_bar_ql = float(ts.barDuration.quarterLength)
            ql = data["quarterLength"]

            next_off = sorted_offsets[i + 1] if i + 1 < len(sorted_offsets) else None
            next_data = raw_measures_by_offset[next_off] if next_off is not None else None

            # Detect if this measure represents a multi-measure rest or a number gap
            if (
                next_off is not None
                and next_data
                and isinstance(next_data["number"], int)
                and isinstance(data["number"], int)
                and next_data["number"] > data["number"] + 1
            ):
                num_bars = next_data["number"] - data["number"]
                ql = max(ql, next_off - off)
            elif ql > standard_bar_ql + 0.01:
                num_bars = max(1, round(ql / standard_bar_ql))
            else:
                num_bars = 1

            bar_ql = ql / num_bars if num_bars > 0 else ql
            base_num = data["number"] if data["number"] is not None else (i + 1)

            for sub_idx in range(num_bars):
                sub_num = (base_num + sub_idx) if isinstance(base_num, int) else f"{base_num}_{sub_idx+1}"
                sub_off = off + (sub_idx * bar_ql)
                sub_dur_ql = bar_ql

                if sub_num == 0:
                    display_num = "0 (Pickup)"
                else:
                    display_num = f"{sub_num}{data['suffix'] if sub_idx == 0 else ''}"

                sub_ts = get_ts_at_offset(sub_off)
                sub_bpm = get_bpm_at_offset(sub_off)
                ts_meta = self.compute_time_signature_meta(sub_ts, sub_bpm, ql=sub_dur_ql)

                # Record meter change milestone
                if ts_meta["time_signature"] != last_recorded_ts_str:
                    meter_changes.append({
                        "measure_number": sub_num,
                        "time_signature": ts_meta["time_signature"],
                        "offset": sub_off,
                        "start_time": offset_to_seconds(sub_off),
                    })
                    last_recorded_ts_str = ts_meta["time_signature"]

                start_sec = offset_to_seconds(sub_off)
                end_sec = offset_to_seconds(sub_off + sub_dur_ql)
                dur_sec = round(max(0.05, end_sec - start_sec), 3)

                # Check which parts have non-rest notes in this measure
                active_parts = []
                resting_parts = []
                for k, p in reconciled_streams.items():
                    m_obj = data["parts_present"].get(k)
                    has_notes = False
                    if m_obj:
                        if num_bars == 1:
                            has_notes = any(not isinstance(n, m21.note.Rest) for n in m_obj.recurse().notes)
                        else:
                            has_notes = any(
                                not isinstance(n, m21.note.Rest)
                                and (sub_off <= (off + float(n.offset)) < sub_off + sub_dur_ql + 0.01)
                                for n in m_obj.recurse().notes
                            )
                    if has_notes:
                        active_parts.append(k)
                    else:
                        resting_parts.append(k)

                measures_list.append({
                    "number": sub_num,
                    "display_number": display_num,
                    "start_time": start_sec,
                    "end_time": end_sec,
                    "duration": dur_sec,
                    "time_signature": ts_meta["time_signature"],
                    "numerator": ts_meta["numerator"],
                    "denominator": ts_meta["denominator"],
                    "beats_per_measure": ts_meta["beats_per_measure"],
                    "beat_unit_ql": ts_meta["beat_unit_ql"],
                    "beat_duration": ts_meta["beat_duration"],
                    "is_compound": ts_meta["is_compound"],
                    "accent_pattern": ts_meta["accent_pattern"],
                    "bpm": round(sub_bpm, 1),
                    "active_parts": active_parts,
                    "resting_parts": resting_parts,
                    "entrances": [],
                })

        # 5. Compute entrances: active in current measure, but was resting in previous measure
        for idx, m_info in enumerate(measures_list):
            if idx == 0:
                m_info["entrances"] = list(m_info["active_parts"])
            else:
                prev_active = set(measures_list[idx - 1]["active_parts"])
                m_info["entrances"] = [k for k in m_info["active_parts"] if k not in prev_active]

        # 6. Compute part-level entrances and extended rest spans
        part_entrances: Dict[str, List[Union[int, str]]] = {k: [] for k in ALL_CHORAL_KEYS}
        part_extended_rests: Dict[str, List[Dict[str, Any]]] = {k: [] for k in ALL_CHORAL_KEYS}

        for m_info in measures_list:
            m_num = m_info["number"]
            for ent_key in m_info["entrances"]:
                if ent_key in part_entrances:
                    part_entrances[ent_key].append(m_num)

        # Calculate extended rest segments for each part (rest span >= 2 measures)
        for key in ALL_CHORAL_KEYS:
            current_rest_start_idx = None

            for idx, m_info in enumerate(measures_list):
                is_active = key in m_info["active_parts"]
                if not is_active:
                    if current_rest_start_idx is None:
                        current_rest_start_idx = idx
                else:
                    if current_rest_start_idx is not None:
                        rest_len = idx - current_rest_start_idx
                        if rest_len >= 2:
                            start_m = measures_list[current_rest_start_idx]
                            end_m = measures_list[idx - 1]
                            next_entry_m = m_info
                            part_extended_rests[key].append({
                                "start_measure": start_m["number"],
                                "end_measure": end_m["number"],
                                "start_time": start_m["start_time"],
                                "end_time": end_m["end_time"],
                                "rest_measures": rest_len,
                                "next_entry_measure": next_entry_m["number"],
                                "next_entry_time": next_entry_m["start_time"],
                            })
                        current_rest_start_idx = None

        initial_ts_str = measures_list[0]["time_signature"] if measures_list else "4/4"

        return {
            "total_measures": len(measures_list),
            "default_bpm": master_tempo_bpm,
            "time_signature": initial_ts_str,
            "time_signatures": meter_changes,
            "total_duration_seconds": measures_list[-1]["end_time"] if measures_list else 0.0,
            "measures": measures_list,
            "part_entrances": part_entrances,
            "part_extended_rests": part_extended_rests,
        }

    def process_and_extract_stems(
        self,
        score: m21.stream.Score,
        output_xml_dir: Path,
        output_midi_dir: Path,
        return_analysis: bool = False,
    ) -> Union[List[ExtractedStem], Tuple[List[ExtractedStem], Dict[str, Any]]]:
        """
        Processes the score, reconciles ALL 11 standard choral parts so every single
        part is always available to select, generates stems, and computes measure analysis.
        """
        output_xml_dir.mkdir(parents=True, exist_ok=True)
        output_midi_dir.mkdir(parents=True, exist_ok=True)

        # ------------------------------------------------------------------
        # 1. Classify all original parts from the score
        # ------------------------------------------------------------------
        extracted_raw: Dict[str, List[m21.stream.Part]] = {
            "piano": [],
            "s1": [],
            "s2": [],
            "soprano": [],
            "a1": [],
            "a2": [],
            "alto": [],
            "t1": [],
            "t2": [],
            "tenor": [],
            "bar1": [],
            "bar2": [],
            "baritone": [],
            "b1": [],
            "b2": [],
            "bass": [],
            "unknown": [],
        }

        for part in score.parts:
            cat = self.identify_part_category(part)
            if cat == "soprano_alto":
                up, low = self.split_polyphonic_staff(part, "Soprano", "Alto")
                extracted_raw["soprano"].append(up)
                extracted_raw["alto"].append(low)
            elif cat == "tenor_bass":
                up, low = self.split_polyphonic_staff(part, "Tenor", "Bass")
                extracted_raw["tenor"].append(up)
                extracted_raw["bass"].append(low)
            elif cat in extracted_raw:
                extracted_raw[cat].append(part)
            else:
                extracted_raw["unknown"].append(part)

        # Resolve unknowns by vocal pitch register
        if extracted_raw["unknown"]:
            for p in extracted_raw["unknown"]:
                reg = self.guess_register_from_notes(p)
                extracted_raw[reg].append(p)

        # ------------------------------------------------------------------
        # 2. Intelligent Choral Reconciliation: Guarantee ALL 11 Parts Exist
        # ------------------------------------------------------------------
        # Base vocal streams
        s1_part: Optional[m21.stream.Part] = None
        s2_part: Optional[m21.stream.Part] = None
        a1_part: Optional[m21.stream.Part] = None
        a2_part: Optional[m21.stream.Part] = None
        t1_part: Optional[m21.stream.Part] = None
        t2_part: Optional[m21.stream.Part] = None
        bar1_part: Optional[m21.stream.Part] = None
        bar2_part: Optional[m21.stream.Part] = None
        b1_part: Optional[m21.stream.Part] = None
        b2_part: Optional[m21.stream.Part] = None

        # Sopranos
        s_pool = extracted_raw["s1"] + extracted_raw["soprano"]
        s2_pool = extracted_raw["s2"]
        if s_pool and s2_pool:
            s1_part = s_pool[0]
            s2_part = s2_pool[0]
        elif len(s_pool) >= 2:
            s1_part = s_pool[0]
            s2_part = s_pool[1]
        elif s_pool:
            if self.check_for_divisi_chords(s_pool[0]):
                s1_part, s2_part = self.split_choral_divisi(s_pool[0], "Soprano I", "Soprano II")
            else:
                s1_part = s_pool[0]
                s2_part = copy.deepcopy(s_pool[0])  # S2 plays S1 notes
        elif s2_pool:
            s1_part = copy.deepcopy(s2_pool[0])
            s2_part = s2_pool[0]

        # Altos
        a_pool = extracted_raw["a1"] + extracted_raw["alto"]
        a2_pool = extracted_raw["a2"]
        if a_pool and a2_pool:
            a1_part = a_pool[0]
            a2_part = a2_pool[0]
        elif len(a_pool) >= 2:
            a1_part = a_pool[0]
            a2_part = a_pool[1]
        elif a_pool:
            if self.check_for_divisi_chords(a_pool[0]):
                a1_part, a2_part = self.split_choral_divisi(a_pool[0], "Alto I", "Alto II")
            else:
                a1_part = a_pool[0]
                a2_part = copy.deepcopy(a_pool[0])  # A2 plays A1 notes
        elif a2_pool:
            a1_part = copy.deepcopy(a2_pool[0])
            a2_part = a2_pool[0]

        # Tenors
        t_pool = extracted_raw["t1"] + extracted_raw["tenor"]
        t2_pool = extracted_raw["t2"]
        if t_pool and t2_pool:
            t1_part = t_pool[0]
            t2_part = t2_pool[0]
        elif len(t_pool) >= 2:
            t1_part = t_pool[0]
            t2_part = t_pool[1]
        elif t_pool:
            if self.check_for_divisi_chords(t_pool[0]):
                t1_part, t2_part = self.split_choral_divisi(t_pool[0], "Tenor I", "Tenor II")
            else:
                t1_part = t_pool[0]
                t2_part = copy.deepcopy(t_pool[0])  # T2 plays T1 notes
        elif t2_pool:
            t1_part = copy.deepcopy(t2_pool[0])
            t2_part = t2_pool[0]

        # Basses
        b_pool = extracted_raw["b1"] + extracted_raw["bass"]
        b2_pool = extracted_raw["b2"]
        if b_pool and b2_pool:
            b1_part = b_pool[0]
            b2_part = b2_pool[0]
        elif len(b_pool) >= 2:
            b1_part = b_pool[0]
            b2_part = b_pool[1]
        elif b_pool:
            if self.check_for_divisi_chords(b_pool[0]):
                b1_part, b2_part = self.split_choral_divisi(b_pool[0], "Bass I", "Bass II")
            else:
                b1_part = b_pool[0]
                b2_part = copy.deepcopy(b_pool[0])  # B2 plays B1 notes!
        elif b2_pool:
            b1_part = copy.deepcopy(b2_pool[0])
            b2_part = b2_pool[0]

        # Baritones
        bar_pool = extracted_raw["bar1"] + extracted_raw["baritone"]
        bar2_pool = extracted_raw["bar2"]
        if bar_pool and bar2_pool:
            bar1_part = bar_pool[0]
            bar2_part = bar2_pool[0]
        elif len(bar_pool) >= 2:
            bar1_part = bar_pool[0]
            bar2_part = bar_pool[1]
        elif bar_pool:
            if self.check_for_divisi_chords(bar_pool[0]):
                bar1_part, bar2_part = self.split_choral_divisi(bar_pool[0], "Baritone I", "Baritone II")
            else:
                bar1_part = bar_pool[0]
                bar2_part = copy.deepcopy(bar_pool[0])
        elif bar2_pool:
            bar1_part = copy.deepcopy(bar2_pool[0])
            bar2_part = bar2_pool[0]
        else:
            # Reconcile Baritone from Tenor & Bass if no explicit Baritone in score
            if t2_part and b1_part:
                bar1_part = copy.deepcopy(t2_part)
                bar2_part = copy.deepcopy(b1_part)
            elif b1_part:
                bar1_part = copy.deepcopy(b1_part)
                bar2_part = copy.deepcopy(b1_part)
            elif t1_part:
                bar1_part = copy.deepcopy(t1_part)
                bar2_part = copy.deepcopy(t1_part)

        # Cross-choir reconciliation fallbacks for missing registers
        # (e.g. TTBB male choir, SSA female choir, or unison)
        primary_vocal = s1_part or a1_part or t1_part or b1_part or (score.parts[0] if score.parts else m21.stream.Part())

        if not s1_part:
            s1_part = copy.deepcopy(t1_part or a1_part or primary_vocal)
        if not s2_part:
            s2_part = copy.deepcopy(s1_part)

        if not a1_part:
            a1_part = copy.deepcopy(s2_part or t1_part or primary_vocal)
        if not a2_part:
            a2_part = copy.deepcopy(a1_part)

        if not t1_part:
            t1_part = copy.deepcopy(a2_part or primary_vocal)
        if not t2_part:
            t2_part = copy.deepcopy(t1_part)

        if not bar1_part:
            bar1_part = copy.deepcopy(t2_part or primary_vocal)
        if not bar2_part:
            bar2_part = copy.deepcopy(bar1_part)

        if not b1_part:
            b1_part = copy.deepcopy(bar2_part or a2_part or primary_vocal)
        if not b2_part:
            b2_part = copy.deepcopy(b1_part)

        # Piano / Accompaniment
        if extracted_raw["piano"]:
            piano_part = self.combine_piano_staves(extracted_raw["piano"])
        else:
            # Create rehearsal piano reduction from vocal parts
            vocal_staves = [p for p in [s1_part, a1_part, t1_part, b1_part] if p is not None]
            piano_part = self.create_choral_reduction_piano(vocal_staves)

        # Build master dictionary of all 11 reconciled parts
        final_parts: Dict[str, Tuple[str, bool, m21.stream.Part, str]] = {
            "Piano": ("Piano Score", True, piano_part, "Accompaniment"),
            "S1": ("Soprano I", False, s1_part, "Soprano I"),
            "S2": ("Soprano II", False, s2_part, "Soprano II"),
            "A1": ("Alto I", False, a1_part, "Alto I"),
            "A2": ("Alto II", False, a2_part, "Alto II"),
            "T1": ("Tenor I", False, t1_part, "Tenor I"),
            "T2": ("Tenor II", False, t2_part, "Tenor II"),
            "Bar1": ("Baritone I", False, bar1_part, "Baritone I"),
            "Bar2": ("Baritone II", False, bar2_part, "Baritone II"),
            "B1": ("Bass I", False, b1_part, "Bass I"),
            "B2": ("Bass II", False, b2_part, "Bass II"),
        }

        # ------------------------------------------------------------------
        # 3. Master Tempo & Timing Analysis
        # ------------------------------------------------------------------
        tempo_marks = list(score.recurse().getElementsByClass(m21.tempo.MetronomeMark))
        master_tempo_bpm = float(tempo_marks[0].number) if (tempo_marks and tempo_marks[0].number) else 100.0
        master_tempo = tempo_marks[0] if tempo_marks else m21.tempo.MetronomeMark(number=master_tempo_bpm)

        # Run Measure Analysis on all 11 parts
        streams_map = {k: v[2] for k, v in final_parts.items()}
        measure_analysis = self.analyze_measures(score, streams_map, master_tempo_bpm=master_tempo_bpm)
        self.last_measure_analysis = measure_analysis

        # ------------------------------------------------------------------
        # 4. Export All 11 Stems to MIDI & MusicXML
        # ------------------------------------------------------------------
        stems_result: List[ExtractedStem] = []

        for key in ALL_CHORAL_KEYS:
            part_name, is_acc, stream_part, orig_name = final_parts[key]
            stream_part = copy.deepcopy(stream_part)
            stream_part.partName = part_name
            stream_part.id = key

            # Assign GM Instrument
            gm_inst = GM_INSTRUMENTS.get(key, m21.instrument.Choir())
            stream_part.insert(0, copy.deepcopy(gm_inst))

            measures_in_part = list(stream_part.getElementsByClass(m21.stream.Measure))
            if measures_in_part:
                first_bar = measures_in_part[0]
                if not first_bar.getElementsByClass(m21.tempo.MetronomeMark):
                    first_bar.insert(0, copy.deepcopy(master_tempo))
            else:
                stream_part.insert(0, copy.deepcopy(master_tempo))

            notes = list(stream_part.recurse().notes)
            note_count = len(notes)
            measure_count = len(stream_part.getElementsByClass(m21.stream.Measure))

            pitch_range = None
            pitches = [n.pitch for n in notes if hasattr(n, "pitch")]
            for chord in [n for n in notes if isinstance(n, m21.chord.Chord)]:
                pitches.extend(chord.pitches)

            if pitches:
                sorted_pitches = sorted(pitches, key=lambda p: p.midi)
                pitch_range = f"{sorted_pitches[0].nameWithOctave} - {sorted_pitches[-1].nameWithOctave}"

            total_ql = stream_part.highestTime
            duration_sec = (total_ql / (master_tempo_bpm / 60.0)) if master_tempo_bpm > 0 else total_ql * 0.6
            duration_sec = round(max(1.0, duration_sec), 2)

            stem_obj = ExtractedStem(
                part_key=key,
                part_name=part_name,
                is_accompaniment=is_acc,
                original_part_name=orig_name,
                stream=stream_part,
                duration_seconds=duration_sec,
                pitch_range=pitch_range,
                measure_count=measure_count,
                note_count=note_count,
            )

            # Export standalone MusicXML
            xml_filename = f"stem_{key}.musicxml"
            xml_path = output_xml_dir / xml_filename
            try:
                stream_part.write("musicxml", fp=str(xml_path))
                stem_obj.xml_path = xml_path
            except Exception as e:
                logger.warning("Could not write MusicXML for stem %s: %s", key, e)

            # Export standalone MIDI
            midi_filename = f"stem_{key}.mid"
            midi_path = output_midi_dir / midi_filename
            try:
                stem_score = m21.stream.Score()
                stem_score.append(stream_part)
                stem_score.write("midi", fp=str(midi_path))
                stem_obj.midi_path = midi_path
            except Exception as e:
                logger.error("Could not write MIDI for stem %s: %s", key, e)

            stems_result.append(stem_obj)
            logger.info(
                "Extracted stem: key=%s, name='%s', notes=%d, duration=%.1fs, range=%s",
                key, part_name, note_count, duration_sec, pitch_range
            )

        if return_analysis:
            return stems_result, measure_analysis
        return stems_result


notation_processor = NotationProcessor()
