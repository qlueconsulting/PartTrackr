from pathlib import Path
import pytest
from music21 import stream, note, meter, tempo

from app.services.audio_synthesizer import AudioSynthesizer

def test_audio_synthesizer_render_and_lockstep_duration(tmp_path: Path):
    s = stream.Score()
    p = stream.Part()
    m = stream.Measure(number=1)
    m.timeSignature = meter.TimeSignature("4/4")
    m.append(tempo.MetronomeMark(number=120.0))
    m.append(note.Note("C4", quarterLength=4.0))
    p.append(m)
    s.append(p)
    
    mid_path = tmp_path / "test.mid"
    s.write("midi", fp=str(mid_path))
    
    synth = AudioSynthesizer()
    target_duration = 2.0 # 2 seconds
    
    wav_path, mp3_path = synth.render_stem(
        midi_path=mid_path,
        stem_name="Piano",
        output_dir=tmp_path / "out",
        target_duration_seconds=target_duration
    )
    
    assert wav_path.exists()
    assert mp3_path.exists()
    assert wav_path.stat().st_size > 0
    assert mp3_path.stat().st_size > 0
    
    # 2 seconds of 44100Hz 16-bit 2-channel PCM = 2 * 44100 * 2 * 2 = 352,800 bytes audio + 44 bytes header = 352,844 bytes
    import wave
    with wave.open(str(wav_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        actual_dur = frames / rate
        assert abs(actual_dur - target_duration) < 0.01, f"Expected {target_duration}s, got {actual_dur}s"
