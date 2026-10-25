from fractions import Fraction
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple
import mido
from mido import MidiFile, MidiTrack, Message, MetaMessage

from common.taxonomy import CANONICAL_11_PARTS, PART_METADATA
from common.cism_schema import ScoreCISM
from common.lockstep_utils import calculate_bar_quarter_length, clamp_and_pad_track_elements

logger = logging.getLogger("decoder_xml_svc.midi")

TICKS_PER_BEAT = 480  # 480 ticks per quarter note


class MIDIGenerator:
    """
    Compiles 11-part CISM JSON into standard 11-channel multi-track MIDI (.mid)
    and produces beat-to-millisecond synchronization maps.
    """

    @classmethod
    def compile_midi_and_sync_map(
        cls,
        cism: ScoreCISM,
        output_dir: Path
    ) -> Tuple[Path, Path, Path, Dict[str, Path], Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        stems_dir = output_dir / "stems"
        stems_dir.mkdir(parents=True, exist_ok=True)

        midi_file = MidiFile(ticks_per_beat=TICKS_PER_BEAT)
        stem_midi_files: Dict[str, MidiFile] = {
            p: MidiFile(ticks_per_beat=TICKS_PER_BEAT) for p in CANONICAL_11_PARTS
        }

        DYNAMIC_VELOCITIES = {
            "ppp": 40, "pp": 50, "p": 62, "mp": 74, "mf": 86, "f": 100, "ff": 114, "fff": 124
        }

        # Conductor / Tempo Track
        conductor_track = MidiTrack()
        conductor_track.append(MetaMessage("track_name", name="Conductor", time=0))
        midi_file.tracks.append(conductor_track)

        all_measures = cism.all_measures()
        initial_bpm = all_measures[0].tempo_bpm if all_measures else 120.0
        tempo_us = int(mido.bpm2tempo(initial_bpm))
        conductor_track.append(MetaMessage("set_tempo", tempo=tempo_us, time=0))

        # Build Conductor Tempo events and Sync Map
        sync_map = {
            "score_title": cism.title,
            "total_measures": len(all_measures),
            "measures": [],
        }

        running_time_ms = 0.0
        current_bpm = initial_bpm
        cond_last_tick = 0
        cumulative_quarters = Fraction(0)

        for m_data in all_measures:
            m_num = m_data.measure_number
            ts = m_data.time_signature
            bpm = m_data.tempo_bpm or current_bpm
            bar_ql = float(calculate_bar_quarter_length(ts))
            ms_per_beat = (60.0 / bpm) * 1000.0
            measure_dur_ms = bar_ql * ms_per_beat

            # Mid-score tempo change in Conductor track
            if abs(bpm - current_bpm) > 0.5:
                current_bpm = bpm
                t_us = int(mido.bpm2tempo(current_bpm))
                t_tick = int(cumulative_quarters * TICKS_PER_BEAT)
                delta_t = max(0, t_tick - cond_last_tick)
                cond_last_tick = t_tick
                conductor_track.append(MetaMessage("set_tempo", tempo=t_us, time=delta_t))

            beats_data = []
            for b_i in range(int(bar_ql)):
                beats_data.append({
                    "beat_index": b_i + 1,
                    "offset_quarters": float(b_i),
                    "time_ms": round(running_time_ms + (b_i * ms_per_beat), 2),
                })

            sync_map["measures"].append({
                "measure_number": m_num,
                "rehearsal_mark": getattr(m_data, "rehearsal_mark", None),
                "start_time_ms": round(running_time_ms, 2),
                "duration_ms": round(measure_dur_ms, 2),
                "time_signature": ts,
                "tempo_bpm": bpm,
                "beats": beats_data,
            })
            running_time_ms += measure_dur_ms
            cumulative_quarters += Fraction(f"{bar_ql:.4f}")

        # Write sync map JSON
        sync_map_path = output_dir / "sync_map.json"
        with open(sync_map_path, "w", encoding="utf-8") as f:
            json.dump(sync_map, f, indent=2)

        # Generate each of the 11 tracks
        stem_paths: Dict[str, Path] = {}

        for p_name in CANONICAL_11_PARTS:
            meta = PART_METADATA[p_name]
            channel = meta["channel"]
            program = meta["gm_program"]
            pan = int(min(127, max(0, int((meta["default_pan"] + 1.0) * 63.5))))

            track = MidiTrack()
            track.append(MetaMessage("track_name", name=meta["display_name"], time=0))
            track.append(Message("program_change", channel=channel, program=program, time=0))
            track.append(Message("control_change", channel=channel, control=10, value=pan, time=0))

            single_midi = stem_midi_files[p_name]
            single_track = MidiTrack()
            single_track.append(MetaMessage("set_tempo", tempo=tempo_us, time=0))
            single_track.append(MetaMessage("track_name", name=meta["display_name"], time=0))
            single_track.append(Message("program_change", channel=0, program=program, time=0))
            single_midi.tracks.append(single_track)

            # Generate chronological note on/off events
            cls._populate_track_notes(track, single_track, all_measures, p_name, channel)

            midi_file.tracks.append(track)

            # Write stem MIDI file
            stem_path = stems_dir / f"{p_name}.mid"
            single_midi.save(str(stem_path))
            stem_paths[p_name] = stem_path

        # Write unified 11-channel MIDI file
        main_midi_path = output_dir / "score_11ch.mid"
        midi_file.save(str(main_midi_path))

        # Write partitioned Piano MIDI file
        piano_midi = MidiFile(ticks_per_beat=TICKS_PER_BEAT)
        piano_midi.tracks.append(conductor_track)
        piano_track_found = [t for t in midi_file.tracks if any(m.type == "track_name" and m.name == PART_METADATA["piano"]["display_name"] for m in t)]
        if piano_track_found:
            piano_midi.tracks.append(piano_track_found[0])
        piano_midi_path = output_dir / "score_piano.mid"
        piano_midi.save(str(piano_midi_path))

        # Write partitioned Vocals MIDI file (all vocal tracks)
        vocals_midi = MidiFile(ticks_per_beat=TICKS_PER_BEAT)
        vocals_midi.tracks.append(conductor_track)
        for t in midi_file.tracks:
            is_piano = any(m.type == "track_name" and m.name == PART_METADATA["piano"]["display_name"] for m in t)
            is_cond = any(m.type == "track_name" and m.name == "Conductor" for m in t)
            if not is_piano and not is_cond:
                vocals_midi.tracks.append(t)
        vocals_midi_path = output_dir / "score_vocals.mid"
        vocals_midi.save(str(vocals_midi_path))

        return main_midi_path, piano_midi_path, vocals_midi_path, stem_paths, sync_map_path

    DYNAMIC_VELOCITIES = {
        "ppp": 40, "pp": 50, "p": 62, "mp": 74, "mf": 86, "f": 100, "ff": 114, "fff": 124
    }

    @classmethod
    def _populate_track_notes(
        cls,
        main_track: MidiTrack,
        single_track: MidiTrack,
        all_measures: List[Any],
        part_name: str,
        channel: int
    ):
        events = []
        cumulative_quarters = Fraction(0)
        active_ties: Dict[int, Fraction] = {}

        for m_data in all_measures:
            bar_ql = calculate_bar_quarter_length(m_data.time_signature)
            t_data = m_data.tracks.get(part_name)
            elems = t_data.elements if t_data else []
            sanitized = clamp_and_pad_track_elements(elems, bar_ql)

            # Base velocity from dynamic mark
            m_dyn = getattr(m_data, "dynamic_mark", None)
            base_vel = cls.DYNAMIC_VELOCITIES.get(m_dyn.lower() if m_dyn else "", 85)

            # Piano sustain pedal down at measure start
            if part_name == "piano":
                events.append((cumulative_quarters, "control_change", 64, 127))
                events.append((cumulative_quarters + bar_ql - Fraction(1, 16), "control_change", 64, 0))

            for el in sanitized:
                if not el.is_rest:
                    pitches_to_emit = []
                    if getattr(el, "is_chord", False) and getattr(el, "chord_pitches", None):
                        for cp in el.chord_pitches:
                            mp = cls._pitch_to_midi(cp)
                            if 0 <= mp <= 127:
                                pitches_to_emit.append(mp)
                    elif el.pitch:
                        mp = el.midi_pitch or cls._pitch_to_midi(el.pitch)
                        if 0 <= mp <= 127:
                            pitches_to_emit.append(mp)

                    # Velocity with metric dynamics and piano touch sensitivity
                    vel = el.velocity or base_vel
                    if el.offset_quarters == 0.0:
                        vel = min(127, vel + 5)
                    elif el.offset_quarters == float(Fraction(bar_ql, 2)):
                        vel = min(127, vel + 2)

                    if part_name == "piano" and not el.velocity:
                        # Acoustic grand piano touch: warm presence
                        vel = max(68, min(118, vel + 3))

                    start_q = cumulative_quarters + Fraction(f"{el.offset_quarters:.4f}")
                    end_q = start_q + Fraction(f"{el.duration_quarters:.4f}")

                    for p_idx, mp in enumerate(pitches_to_emit):
                        is_tie_continue = getattr(el, "tie", None) in ("continue", "stop")
                        is_tie_start = getattr(el, "tie", None) in ("start", "continue")

                        # Voicing: bass note slightly firmer for grand piano fullness
                        note_vel = vel
                        if part_name == "piano" and len(pitches_to_emit) > 1 and p_idx == 0:
                            note_vel = min(127, vel + 4)

                        if not is_tie_continue or mp not in active_ties:
                            events.append((start_q, "note_on", mp, note_vel))
                            active_ties[mp] = start_q

                        if not is_tie_start:
                            events.append((end_q, "note_off", mp, 0))
                            if mp in active_ties:
                                del active_ties[mp]

            cumulative_quarters += bar_ql

        events.sort(key=lambda x: (x[0], 0 if x[1] in ("note_off", "control_change") else 1))

        last_tick = 0
        for q_time, ev_type, note_or_ctrl, vel in events:
            tick_time = int(q_time * TICKS_PER_BEAT)
            delta = max(0, tick_time - last_tick)
            last_tick = tick_time

            if ev_type == "control_change":
                main_msg = Message("control_change", channel=channel, control=note_or_ctrl, value=vel, time=delta)
                single_msg = Message("control_change", channel=0, control=note_or_ctrl, value=vel, time=delta)
            else:
                main_msg = Message(ev_type, channel=channel, note=note_or_ctrl, velocity=vel, time=delta)
                single_msg = Message(ev_type, channel=0, note=note_or_ctrl, velocity=vel, time=delta)

            main_track.append(main_msg)
            single_track.append(single_msg)

        main_track.append(MetaMessage("end_of_track", time=TICKS_PER_BEAT))
        single_track.append(MetaMessage("end_of_track", time=TICKS_PER_BEAT))

    @staticmethod
    def _pitch_to_midi(pitch_str: str) -> int:
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
