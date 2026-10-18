from fractions import Fraction
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple
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
    def compile_score(
        cls,
        cism: ScoreCISM,
        output_dir: Path
    ) -> Tuple[Path, Dict[str, Path], List[Dict[str, Any]]]:
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

        # Add StaffGroups for bracket / brace
        sc.append(layout.StaffGroup(vocal_parts, symbol="bracket", name="Choir"))
        if piano_parts:
            sc.append(layout.StaffGroup(piano_parts, symbol="brace", name="Piano"))

        # Flatten measures in order
        all_measures = cism.all_measures()
        measure_summary = []
        cumulative_seconds = 0.0

        current_ts_str = "4/4"
        current_tempo_bpm = 120.0

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

                track_data = m_data.tracks.get(p_name)
                elements = track_data.elements if track_data else []

                # Enforce Rule B clamping & padding
                sanitized_elems = clamp_and_pad_track_elements(elements, bar_ql)

                has_notes = False
                for el in sanitized_elems:
                    if el.is_rest or not el.pitch:
                        r = note.Rest(quarterLength=float(el.duration_quarters))
                        m_part.insert(float(el.offset_quarters), r)
                    else:
                        has_notes = True
                        n = note.Note(el.pitch, quarterLength=float(el.duration_quarters))
                        if el.lyric:
                            n.lyric = el.lyric
                        m_part.insert(float(el.offset_quarters), n)

                if has_notes:
                    active_parts.append(p_name)
                else:
                    resting_parts.append(p_name)

                parts[p_name].append(m_part)

            measure_summary.append({
                "measure_number": m_num,
                "start_time_seconds": round(cumulative_seconds, 3),
                "duration_seconds": round(duration_s, 3),
                "quarter_length": float(bar_ql),
                "time_signature": ts_str,
                "tempo_bpm": tempo_bpm,
                "active_parts": active_parts,
                "resting_parts": resting_parts,
            })
            cumulative_seconds += duration_s

        for p_name in CANONICAL_11_PARTS:
            sc.append(parts[p_name])

        # Write unified full score MusicXML
        main_xml_path = output_dir / "score.musicxml"
        sc.write("musicxml", fp=str(main_xml_path))

        # Write individual stem MusicXML files
        stem_paths: Dict[str, Path] = {}
        for p_name in CANONICAL_11_PARTS:
            single_sc = stream.Score()
            single_sc.metadata = sc.metadata
            single_sc.append(parts[p_name])
            stem_xml = stems_dir / f"{p_name}.musicxml"
            single_sc.write("musicxml", fp=str(stem_xml))
            stem_paths[p_name] = stem_xml

        return main_xml_path, stem_paths, measure_summary
