import wave
from pathlib import Path
import music21 as m21
import pytest

from app.services.synthesis import audio_synthesizer


def test_audio_synthesis_rendering(tmp_path):
    """Test synthesizing a MIDI file to a playable WAV audio stem."""
    # Create simple MIDI file using music21
    score = m21.stream.Score()
    part = m21.stream.Part()
    m = m21.stream.Measure(number=1)
    m.append(m21.note.Note("A4", quarterLength=2))
    m.append(m21.note.Note("C5", quarterLength=2))
    part.append(m)
    score.append(part)

    midi_file = tmp_path / "test_stem.mid"
    score.write("midi", fp=str(midi_file))

    out_audio_dir = tmp_path / "audio"
    audio_file = audio_synthesizer.render_stem(
        midi_path=midi_file,
        output_audio_dir=out_audio_dir,
        stem_key="S1",
        is_piano=False,
    )

    assert audio_file.exists()
    assert audio_file.stat().st_size > 1000

    # Validate that it is a valid 44.1kHz 16-bit stereo WAV
    with wave.open(str(audio_file), "rb") as wf:
        assert wf.getnchannels() == 2      # Stereo
        assert wf.getsampwidth() == 2      # 16-bit PCM
        assert wf.getframerate() == 44100  # 44.1kHz
        frames = wf.getnframes()
        duration = frames / 44100.0
        assert duration > 1.0


def test_piano_vs_vocal_synthesis(tmp_path):
    """Test synthesis with is_piano flag."""
    score = m21.stream.Score()
    part = m21.stream.Part()
    m = m21.stream.Measure(number=1)
    m.append(m21.chord.Chord(["C3", "E3", "G3"], quarterLength=2))
    part.append(m)
    score.append(part)

    midi_file = tmp_path / "piano_stem.mid"
    score.write("midi", fp=str(midi_file))

    audio_file = audio_synthesizer.render_stem(
        midi_path=midi_file,
        output_audio_dir=tmp_path / "audio",
        stem_key="Piano",
        is_piano=True,
    )

    assert audio_file.exists()
    assert audio_file.stat().st_size > 1000
