from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stem import Stem

router = APIRouter(prefix="/scores/{score_id}/stems", tags=["Stems"])


@router.get("/{stem_id}/audio")
def get_stem_audio(score_id: str, stem_id: str, db: Session = Depends(get_db)):
    """
    Streams the audio file (WAV or MP3) for a given stem.
    Provides standard audio headers and CORS support for Web Audio API fetch/decode.
    """
    stem = db.query(Stem).filter(Stem.id == stem_id, Stem.score_id == score_id).first()
    if not stem or not stem.audio_path or not Path(stem.audio_path).exists():
        raise HTTPException(status_code=404, detail="Audio file not found for this stem")

    path = Path(stem.audio_path)
    media_type = "audio/mpeg" if path.suffix.lower() == ".mp3" else "audio/wav"

    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=path.name,
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/{stem_id}/midi")
def get_stem_midi(score_id: str, stem_id: str, db: Session = Depends(get_db)):
    """Downloads the isolated MIDI file for a given stem."""
    stem = db.query(Stem).filter(Stem.id == stem_id, Stem.score_id == score_id).first()
    if not stem or not stem.midi_path or not Path(stem.midi_path).exists():
        raise HTTPException(status_code=404, detail="MIDI file not found for this stem")

    path = Path(stem.midi_path)
    return FileResponse(
        path=str(path),
        media_type="audio/midi",
        filename=path.name,
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )
