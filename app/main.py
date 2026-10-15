from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.database import engine, Base, run_sqlite_migrations
from app.api.v1 import api_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("parttrackr")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create DB tables & run migrations for existing databases
    logger.info("Initializing PartTrackr database schema...")
    Base.metadata.create_all(bind=engine)
    run_sqlite_migrations(engine)
    logger.info("Database schema initialized and verified.")
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

from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail if isinstance(exc.detail, str) else str(exc.detail)}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": f"Validation error: {exc.errors()}"}
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request, exc: Exception):
    logger.exception(f"Unhandled error processing request to {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Score processing error: {str(exc)}"}
    )

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
