from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.database import engine, Base
from app.api.v1 import api_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("parttrackr")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create DB tables
    logger.info("Initializing PartTrackr database schema...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database schema initialized.")
    yield
    # Shutdown
    logger.info("Shutting down PartTrackr...")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Automated Choral OMR, Stem Isolation, & Rehearsal Player Microservice",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# Static file mount for raw storage if needed
app.mount("/storage", StaticFiles(directory=str(settings.STORAGE_DIR)), name="storage")

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "taxonomy_stems": 11,
        "audiveris_configured": settings.AUDIVERIS_CMD,
        "fluidsynth_configured": settings.FLUIDSYNTH_CMD
    }

# Frontend static serving if built
frontend_dist = settings.BASE_DIR / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = frontend_dist / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dist / "index.html")
