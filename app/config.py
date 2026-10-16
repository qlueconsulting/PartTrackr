import os
from pathlib import Path
from pydantic import BaseModel

class Settings(BaseModel):
    PROJECT_NAME: str = "PartTrackr"
    API_V1_PREFIX: str = "/api/v1"
    
    # Base directories
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    STORAGE_DIR: Path = BASE_DIR / "storage"
    SOUNDFONTS_DIR: Path = BASE_DIR / "soundfonts"
    
    # External tool CLI paths
    AUDIVERIS_CMD: str = os.getenv("AUDIVERIS_CMD", "audiveris")
    FLUIDSYNTH_CMD: str = os.getenv("FLUIDSYNTH_CMD", "fluidsynth")
    FFMPEG_CMD: str = os.getenv("FFMPEG_CMD", "ffmpeg")
    SOUNDFONT_PATH: str = os.getenv(
        "SOUNDFONT_PATH",
        str(BASE_DIR / "soundfonts" / "GeneralUser_GS.sf2")
    )
    
    # Fallback system soundfont paths commonly on Linux
    SYSTEM_SOUNDFONT_PATHS: list[str] = [
        "/usr/share/sounds/sf2/FluidR3_GM.sf2",
        "/usr/share/sounds/sf2/default.sf2",
        "/usr/share/soundfonts/default.sf2",
        "/usr/share/sounds/sf2/fluid-soundfont-gm.sf2"
    ]
    
    # Database URL
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/parttrackr.db")
    
    # Real-Time LLM & MCP Sheet Music Intelligence Settings
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://192.168.2.4:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b")
    MCP_SERVER_URL: str = os.getenv("MCP_SERVER_URL", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    
    # CORS
    CORS_ORIGINS: list[str] = ["*"]

settings = Settings()

# Ensure directories exist
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
settings.SOUNDFONTS_DIR.mkdir(parents=True, exist_ok=True)
