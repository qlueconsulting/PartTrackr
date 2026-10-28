from fractions import Fraction
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
import music21
from music21 import stream, note, chord, meter, tempo, clef, layout, metadata

from common.taxonomy import CANONICAL_11_PARTS, PART_METADATA
from common.cism_schema import ScoreCISM, MeasureData, TrackData, NoteElement
from common.lockstep_utils import calculate_bar_quarter_length, clamp_and_pad_track_elements

logger = logging.getLogger("decoder_xml_svc.compiler")


class XMLCompiler:
    """
    Validates beat counts and compiles 11-part CISM JSON into standard MusicXML (.musicxml).
    Enforces Rule B: Metric Lockstep Synchronization (Fraction duration safety, zero drift).
    """

    @classmethod
    def _quantize_musicxml_duration(cls, dur: float) -> float:
        """Snaps arbitrary floating point durations to standard expressible MusicXML durations."""
        if dur >= 3.5:
            return 4.0
        elif dur >= 2.5:
            return 3.0
        elif dur >= 1.75:
            return 2.0
        elif dur >= 1.25:
            return 1.5
        elif dur >= 0.85:
            return 1.0
        elif dur >= 0.65:
            return 0.75
        elif dur >= 0.35:
            return 0.5
        else:
            return 0.25

    @classmethod
    def _pitch_to_midi_num(cls, pitch_str: Optional[str]) -> int:
        if not pitch_str:
            return 60
        import re
        m = re.match(r"^([A-Ga-g])([#b]?)(-?\d+)$", pitch_str.strip())
        if not m:
            return 60
        step, acc, oct_str = m.groups()
        step = step.upper()
        octave = int(oct_str)
        note_map = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
        val = note_map.get(step, 0)
        if acc == "#":
            val += 1
        elif acc == "b":
            val -= 1
        return (octave + 1) * 12 + val

    @classmethod
    def _populate_measure_from_elements(
        cls,
        m_part: music21.stream.Measure,
        elements: List[NoteElement],
        bar_ql: Fraction
    ) -> bool:
        sanitized_elems = clamp_and_pad_track_elements(elements, bar_ql)
        has_notes = False
        for el in sanitized_elems:
            raw_dur = float(el.duration_quarters)
            valid_dur = cls._quantize_musicxml_duration(raw_dur)
            if valid_dur <= 0.05:
                continue

            off_val = round(float(el.offset_quarters) * 4.0) / 4.0

            if el.is_rest or not el.pitch:
                r = note.Rest(quarterLength=valid_dur)
                m_part.insert(off_val, r)
            else:
                has_notes = True
                try:
                    if el.is_chord and el.chord_pitches and len(el.chord_pitches) >= 2:
                        ch = chord.Chord(el.chord_pitches, quarterLength=valid_dur)
                        if el.lyric:
                            ch.lyric = el.lyric
                        if el.tie:
                            ch.tie = music21.tie.Tie(el.tie)
                        m_part.insert(off_val, ch)
                    else:
                        n = note.Note(el.pitch, quarterLength=valid_dur)
                        if el.lyric:
                            n.lyric = el.lyric
                        if el.tie:
                            n.tie = music21.tie.Tie(el.tie)
                        m_part.insert(off_val, n)
                except Exception:
                    r = note.Rest(quarterLength=valid_dur)
                    m_part.insert(off_val, r)
        return has_notes

    @classmethod
    def compile_score(
        cls,
        cism: ScoreCISM,
        output_dir: Path
    ) -> Tuple[Path, Path, Path, Dict[str, Path], List[Dict[str, Any]]]:
        output_dir.mkdir(parents=True, exist_ok=True)
        stems_dir = output_dir / "stems"
        stems_dir.mkdir(parents=True, exist_ok=True)

        sc = stream.Score()
        sc.metadata = metadata.Metadata()
        sc.metadata.title = cism.title
        sc.metadata.composer = cism.composer

        # Prepare 11 music21 Parts
        parts: Dict[str, music21.stream.Part] = {}
        vocal_parts: List[music21.stream.Part] = []
        piano_parts: List[music21.stream.Part] = []

        for p_name in CANONICAL_11_PARTS:
            meta = PART_METADATA[p_name]
            p = stream.Part(id=p_name)
            p.partName = meta["display_name"]
            p.partAbbreviation = p_name

            inst = music21.instrument.Instrument()
            inst.midiProgram = meta["gm_program"]
            p.insert(0, inst)

            # Assign clef
            default_clef = meta["default_clef"]
            if default_clef == "treble":
                p.insert(0, clef.TrebleClef())
            elif default_clef == "treble_8vb":
                p.insert(0, clef.Treble8vbClef())
            elif default_clef == "bass":
                p.insert(0, clef.BassClef())
            elif default_clef == "grand":
                p.insert(0, clef.TrebleClef())

            parts[p_name] = p
            if p_name == "piano":
                piano_parts.append(p)
            else:
                vocal_parts.append(p)

        # Flatten measures in order
        all_measures = cism.all_measures()
        measure_summary = []
        cumulative_seconds = 0.0

        current_ts_str = "4/4"
        current_tempo_bpm = 120.0

        # Dedicated 2-staff Piano Score (Piano RH Treble + Piano LH Bass in curly brace)
        sc_piano = stream.Score()
        sc_piano.metadata = sc.metadata
        p_piano_rh = stream.Part(id="piano_rh")
        p_piano_rh.partName = "Piano RH"
        p_piano_rh.partAbbreviation = "Pno."
        p_piano_rh.insert(0, clef.TrebleClef())
        inst_rh = music21.instrument.Instrument()
        inst_rh.midiProgram = 0
        p_piano_rh.insert(0, inst_rh)

        p_piano_lh = stream.Part(id="piano_lh")
        p_piano_lh.partName = "Piano LH"
        p_piano_lh.partAbbreviation = "Pno."
        p_piano_lh.insert(0, clef.BassClef())
        inst_lh = music21.instrument.Instrument()
        inst_lh.midiProgram = 0
        p_piano_lh.insert(0, inst_lh)

        sc_piano.append(layout.StaffGroup([p_piano_rh, p_piano_lh], symbol="brace", name="Piano"))

        for m_idx, m_data in enumerate(all_measures):
            m_num = m_data.measure_number
            ts_str = m_data.time_signature or current_ts_str
            tempo_bpm = m_data.tempo_bpm or current_tempo_bpm
            current_ts_str = ts_str
            current_tempo_bpm = tempo_bpm

            bar_ql = calculate_bar_quarter_length(ts_str)
            duration_s = float(bar_ql) * (60.0 / tempo_bpm)

            active_parts = []
            resting_parts = []

            for p_name in CANONICAL_11_PARTS:
                m_part = stream.Measure(number=m_num)
                if m_idx == 0 or (m_idx > 0 and all_measures[m_idx - 1].time_signature != ts_str):
                    m_part.timeSignature = meter.TimeSignature(ts_str)
                if m_idx == 0 or (m_idx > 0 and all_measures[m_idx - 1].tempo_bpm != tempo_bpm):
                    m_part.insert(0, tempo.MetronomeMark(number=tempo_bpm))
                if getattr(m_data, "rehearsal_mark", None):
                    m_part.insert(0, music21.expressions.RehearsalMark(m_data.rehearsal_mark))

                track_data = m_data.tracks.get(p_name)
                elements = track_data.elements if track_data else []

                has_notes = cls._populate_measure_from_elements(m_part, elements, bar_ql)
                if has_notes:
                    active_parts.append(p_name)
                else:
                    resting_parts.append(p_name)

                parts[p_name].append(m_part)

            # Build synchronized measures for 2-staff piano partition
            m_rh = stream.Measure(number=m_num)
            m_lh = stream.Measure(number=m_num)
            if m_idx == 0 or (m_idx > 0 and all_measures[m_idx - 1].time_signature != ts_str):
                m_rh.timeSignature = meter.TimeSignature(ts_str)
                m_lh.timeSignature = meter.TimeSignature(ts_str)
            if m_idx == 0 or (m_idx > 0 and all_measures[m_idx - 1].tempo_bpm != tempo_bpm):
                m_rh.insert(0, tempo.MetronomeMark(number=tempo_bpm))
                m_lh.insert(0, tempo.MetronomeMark(number=tempo_bpm))
            if getattr(m_data, "rehearsal_mark", None):
                m_rh.insert(0, music21.expressions.RehearsalMark(m_data.rehearsal_mark))
                m_lh.insert(0, music21.expressions.RehearsalMark(m_data.rehearsal_mark))

            # 1. First priority: dedicated piano_rh and piano_lh tracks from router
            track_rh = m_data.tracks.get("piano_rh")
            track_lh = m_data.tracks.get("piano_lh")
            rh_elems = []
            lh_elems = []

            if track_rh and any(not el.is_rest for el in track_rh.elements):
                rh_elems = track_rh.elements
            if track_lh and any(not el.is_rest for el in track_lh.elements):
                lh_elems = track_lh.elements

            # 2. Second priority: pre-routing raw staves from OMR if present
            if not rh_elems or not lh_elems:
                raw_rh = None
                raw_lh = None
                for sys_obj in cism.systems:
                    for st_info in sys_obj.staves:
                        if st_info.role == "piano_rh" and st_info.staff_id in m_data.raw_staves:
                            raw_rh = m_data.raw_staves[st_info.staff_id]
                        elif st_info.role == "piano_lh" and st_info.staff_id in m_data.raw_staves:
                            raw_lh = m_data.raw_staves[st_info.staff_id]
                if not rh_elems and raw_rh and any(not el.is_rest for el in raw_rh.elements):
                    rh_elems = raw_rh.elements
                if not lh_elems and raw_lh and any(not el.is_rest for el in raw_lh.elements):
                    lh_elems = raw_lh.elements

            # 3. Fallback: split unified piano track diatonically around Middle C (MIDI 60)
            if not rh_elems and not lh_elems:
                p_track = m_data.tracks.get("piano")
                p_elems = p_track.elements if p_track else []
                for el in p_elems:
                    if el.is_rest:
                        continue
                    mp = el.midi_pitch or cls._pitch_to_midi_num(el.pitch)
                    if mp >= 60:
                        rh_elems.append(el)
                    else:
                        lh_elems.append(el)

            # Pad empty hand measures with whole rests
            whole_rest_el = [NoteElement(pitch=None, duration_quarters=float(bar_ql), duration_type="whole", is_rest=True)]
            if not rh_elems:
                rh_elems = whole_rest_el
            if not lh_elems:
                lh_elems = whole_rest_el

            cls._populate_measure_from_elements(m_rh, rh_elems, bar_ql)
            cls._populate_measure_from_elements(m_lh, lh_elems, bar_ql)
            p_piano_rh.append(m_rh)
            p_piano_lh.append(m_lh)

            measure_summary.append({
                "measure_number": m_num,
                "rehearsal_mark": getattr(m_data, "rehearsal_mark", None),
                "start_time_seconds": round(cumulative_seconds, 3),
                "duration_seconds": round(duration_s, 3),
                "quarter_length": float(bar_ql),
                "time_signature": ts_str,
                "tempo_bpm": tempo_bpm,
                "active_parts": active_parts,
                "resting_parts": resting_parts,
            })
            cumulative_seconds += duration_s

        # Assemble unified full score MusicXML (score.musicxml)
        is_piano_only = bool((cism.metadata or {}).get("piano_only"))

        # Filter vocal parts to those with active notes so the choir staves sit directly adjacent to piano staves
        active_vocal_parts = [
            vp for vp in vocal_parts
            if any(any(isinstance(el, (note.Note, chord.Chord)) for el in m.recurse().getElementsByClass(note.GeneralNote)) for m in vp.getElementsByClass(stream.Measure))
        ]
        chosen_vocal_parts = active_vocal_parts if active_vocal_parts else vocal_parts

        if is_piano_only or (not active_vocal_parts and cism.has_piano):
            # Piano-only extraction: score.musicxml contains strictly the Keyboard Grand Staff
            sc.append(layout.StaffGroup([p_piano_rh, p_piano_lh], symbol="brace", name="Piano", abbreviation="Pno."))
            sc.append(p_piano_rh)
            sc.append(p_piano_lh)
        else:
            sc.append(layout.StaffGroup(chosen_vocal_parts, symbol="bracket", name="Choir"))
            for vp in chosen_vocal_parts:
                sc.append(vp)

            if cism.has_piano:
                sc.append(layout.StaffGroup([p_piano_rh, p_piano_lh], symbol="brace", name="Piano", abbreviation="Pno."))
                sc.append(p_piano_rh)
                sc.append(p_piano_lh)
            else:
                # If a cappella, still provide piano part if requested
                sc.append(parts["piano"])

        main_xml_path = output_dir / "score.musicxml"
        sc.write("musicxml", fp=str(main_xml_path))

        # Write partitioned Vocals-only MusicXML (score_vocals.musicxml)
        sc_vocals = stream.Score()
        sc_vocals.metadata = sc.metadata
        sc_vocals.append(layout.StaffGroup(chosen_vocal_parts, symbol="bracket", name="Choir"))
        for vp in chosen_vocal_parts:
            sc_vocals.append(vp)
        vocals_xml_path = output_dir / "score_vocals.musicxml"
        sc_vocals.write("musicxml", fp=str(vocals_xml_path))

        # Write partitioned Piano-only MusicXML (score_piano.musicxml) with 2 staves (RH Treble + LH Bass)
        sc_piano.append(p_piano_rh)
        sc_piano.append(p_piano_lh)
        piano_xml_path = output_dir / "score_piano.musicxml"
        sc_piano.write("musicxml", fp=str(piano_xml_path))

        # Write individual stem MusicXML files
        stem_paths: Dict[str, Path] = {}
        for p_name in CANONICAL_11_PARTS:
            single_sc = stream.Score()
            single_sc.metadata = sc.metadata
            if p_name == "piano" and cism.has_piano:
                single_sc.append(layout.StaffGroup([p_piano_rh, p_piano_lh], symbol="brace", name="Piano", abbreviation="Pno."))
                single_sc.append(p_piano_rh)
                single_sc.append(p_piano_lh)
            else:
                single_sc.append(parts[p_name])
            stem_xml = stems_dir / f"{p_name}.musicxml"
            single_sc.write("musicxml", fp=str(stem_xml))
            stem_paths[p_name] = stem_xml

        return main_xml_path, piano_xml_path, vocals_xml_path, stem_paths, measure_summary
