import os
from pathlib import Path
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseModel):
    APP_NAME: str = "PartTrackr"
    VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "true").lower() in ("true", "1", "yes")

    # Storage paths
    STORAGE_DIR: Path = Path(os.getenv("STORAGE_DIR", str(BASE_DIR / "storage")))
    UPLOAD_DIR: Path = STORAGE_DIR / "uploads"
    XML_DIR: Path = STORAGE_DIR / "xml"
    STEMS_DIR: Path = STORAGE_DIR / "stems"
    MIDI_DIR: Path = STORAGE_DIR / "midi"

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'parttrackr_local.db'}"
    )

    # Binaries and external tools
    AUDIVERIS_BIN: str = os.getenv("AUDIVERIS_BIN", "audiveris")
    FLUIDSYNTH_BIN: str = os.getenv("FLUIDSYNTH_BIN", "fluidsynth")
    FFMPEG_BIN: str = os.getenv("FFMPEG_BIN", "ffmpeg")
    SOUNDFONT_PATH: str = os.getenv(
        "SOUNDFONT_PATH",
        "/usr/share/sounds/sf2/FluidR3_GM.sf2"
    )

    def init_storage(self):
        """Ensure all storage directories exist."""
        for path in [self.STORAGE_DIR, self.UPLOAD_DIR, self.XML_DIR, self.STEMS_DIR, self.MIDI_DIR]:
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.init_storage()
