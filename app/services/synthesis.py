import logging
import math
import os
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from typing import Optional

import mido
import numpy as np

from app.config import settings

logger = logging.getLogger("parttrackr.synthesis")


class AudioSynthesizer:
    """
    Renders MIDI stems into audio (WAV / MP3).
    Uses FluidSynth CLI with SoundFont in production / Docker.
    Falls back to high-quality built-in additive harmonic synthesizer
    when FluidSynth or SoundFont is unavailable (e.g. local dev / testing).
    """

    def __init__(
        self,
        fluidsynth_bin: Optional[str] = None,
        soundfont_path: Optional[str] = None,
        ffmpeg_bin: Optional[str] = None,
    ):
        self.fluidsynth_bin = fluidsynth_bin or settings.FLUIDSYNTH_BIN
        self.soundfont_path = soundfont_path or settings.SOUNDFONT_PATH
        self.ffmpeg_bin = ffmpeg_bin or settings.FFMPEG_BIN

    def has_fluidsynth(self) -> bool:
        """Check if fluidsynth CLI is installed and soundfont exists."""
        bin_ok = shutil.which(self.fluidsynth_bin) is not None
        sf_ok = Path(self.soundfont_path).exists() if self.soundfont_path else False
        return bin_ok and sf_ok

    def has_ffmpeg(self) -> bool:
        """Check if ffmpeg CLI is installed."""
        return shutil.which(self.ffmpeg_bin) is not None

    def render_stem(
        self, midi_path: Path, output_audio_dir: Path, stem_key: str, is_piano: bool = False
    ) -> Path:
        """
        Renders a single MIDI stem file to audio (WAV/MP3).
        Returns Path to the resulting audio file.
        """
        midi_path = Path(midi_path).resolve()
        output_audio_dir = Path(output_audio_dir).resolve()
        output_audio_dir.mkdir(parents=True, exist_ok=True)

        wav_path = output_audio_dir / f"{midi_path.stem}.wav"
        mp3_path = output_audio_dir / f"{midi_path.stem}.mp3"

        if self.has_fluidsynth():
            logger.info("Synthesizing %s using FluidSynth with %s", midi_path.name, self.soundfont_path)
            self._render_fluidsynth(midi_path, wav_path)
        else:
            logger.info(
                "FluidSynth/SoundFont not found. Synthesizing %s using built-in harmonic synth.",
                midi_path.name,
            )
            self._render_fallback_synth(midi_path, wav_path, is_piano=is_piano)

        # Convert to MP3 if FFmpeg is available
        if self.has_ffmpeg():
            try:
                self._convert_to_mp3(wav_path, mp3_path)
                return mp3_path
            except Exception as e:
                logger.warning("FFmpeg MP3 conversion failed, serving WAV: %s", e)
                return wav_path

        return wav_path

    def _render_fluidsynth(self, midi_path: Path, wav_path: Path):
        """Invoke FluidSynth CLI to render MIDI to WAV."""
        cmd = [
            self.fluidsynth_bin,
            "-ni",
            "-F",
            str(wav_path),
            "-r",
            "44100",
            str(self.soundfont_path),
            str(midi_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
            if result.returncode != 0:
                logger.error("FluidSynth error (code %d): %s", result.returncode, result.stderr)
                raise RuntimeError(f"FluidSynth failed: {result.stderr}")
        except Exception as exc:
            logger.warning("FluidSynth execution failed (%s), falling back to internal synth", exc)
            self._render_fallback_synth(midi_path, wav_path, is_piano=("piano" in midi_path.stem.lower()))

    def _convert_to_mp3(self, wav_path: Path, mp3_path: Path):
        """Convert WAV to MP3 using FFmpeg."""
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i",
            str(wav_path),
            "-codec:a",
            "libmp3lame",
            "-qscale:a",
            "2",
            str(mp3_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {res.stderr}")

    def _render_fallback_synth(self, midi_path: Path, wav_path: Path, is_piano: bool = False):
        """
        Pure Python + numpy harmonic synthesizer.
        Parses MIDI note events and generates crisp, clean audio with ADSR envelope.
        """
        sample_rate = 44100
        mid = mido.MidiFile(str(midi_path))

        # Collect note events with exact absolute timestamps (in seconds)
        active_notes = {}  # note_num: (start_time, velocity)
        completed_notes = []  # (start_time, end_time, note_num, velocity)
        current_time = 0.0

        for msg in mid:
            current_time += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                active_notes[msg.note] = (current_time, msg.velocity)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                if msg.note in active_notes:
                    start_t, vel = active_notes.pop(msg.note)
                    completed_notes.append((start_t, current_time, msg.note, vel))

        # Close any lingering notes
        for note_num, (start_t, vel) in active_notes.items():
            completed_notes.append((start_t, current_time + 1.0, note_num, vel))

        # Total duration
        total_duration = max(current_time + 1.0, 1.0)
        total_samples = int(math.ceil(total_duration * sample_rate))
        audio = np.zeros(total_samples, dtype=np.float32)

        # Harmonics profiles
        if is_piano:
            # Piano profile: sharp attack, rich early harmonics, exponential decay
            harmonics = [(1.0, 1.0), (2.0, 0.6), (3.0, 0.35), (4.0, 0.2), (5.0, 0.1)]
        else:
            # Choral Vocal profile: warm choral formant harmonics, smooth sustained tone
            harmonics = [(1.0, 1.0), (2.0, 0.75), (3.0, 0.5), (4.0, 0.3), (5.0, 0.15), (6.0, 0.08)]

        for start_t, end_t, note_num, velocity in completed_notes:
            start_idx = int(start_t * sample_rate)
            dur = max(end_t - start_t, 0.08)
            num_samples = int(dur * sample_rate)
            if start_idx + num_samples > total_samples:
                num_samples = total_samples - start_idx
            if num_samples <= 0:
                continue

            # MIDI note to frequency: f = 440 * 2^((n - 69) / 12)
            freq = 440.0 * (2.0 ** ((note_num - 69) / 12.0))
            t = np.arange(num_samples) / sample_rate

            # Additive synthesis over harmonic series
            note_wave = np.zeros(num_samples, dtype=np.float32)
            for h_mult, h_amp in harmonics:
                note_wave += h_amp * np.sin(2.0 * np.pi * freq * h_mult * t)

            # ADSR Envelope
            envelope = np.ones(num_samples, dtype=np.float32)
            if is_piano:
                # Fast attack 10ms, exponential decay
                att_len = min(int(0.01 * sample_rate), num_samples)
                if att_len > 0:
                    envelope[:att_len] = np.linspace(0.0, 1.0, att_len)
                # Exponential decay over the note duration
                decay_rate = 2.5
                decay_env = np.exp(-decay_rate * (t / dur))
                envelope *= decay_env
            else:
                # Choral voice envelope: gentle attack 40ms, sustain, release 60ms
                att_len = min(int(0.04 * sample_rate), num_samples // 2)
                rel_len = min(int(0.06 * sample_rate), num_samples // 2)
                if att_len > 0:
                    envelope[:att_len] = np.linspace(0.0, 1.0, att_len)
                if rel_len > 0:
                    envelope[-rel_len:] *= np.linspace(1.0, 0.0, rel_len)

            vel_scale = (velocity / 127.0) * 0.4
            audio[start_idx : start_idx + num_samples] += note_wave * envelope * vel_scale

        # Normalize audio to prevent clipping
        max_amp = np.max(np.abs(audio))
        if max_amp > 1e-4:
            audio = (audio / max_amp) * 0.90

        # Convert float32 to int16 stereo WAV
        int16_audio = (audio * 32767.0).astype(np.int16)
        stereo_audio = np.column_stack((int16_audio, int16_audio))

        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(2)      # Stereo
            wf.setsampwidth(2)      # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(stereo_audio.tobytes())

        logger.info("Rendered fallback audio stem: %s (duration: %.2fs)", wav_path.name, total_duration)


audio_synthesizer = AudioSynthesizer()
