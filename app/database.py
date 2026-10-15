import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

# SQLite needs connect_args check_same_thread=False
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def run_sqlite_migrations(target_engine=None):
    """
    Ensures all columns exist in the SQLite database even if the database
    was initialized with an older schema on persistent Docker volumes.
    """
    eng = target_engine or engine
    if not str(eng.url).startswith("sqlite"):
        return

    try:
        with eng.connect() as conn:
            # Check if table scores exists
            res = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='scores';")).fetchone()
            if not res:
                return

            result = conn.execute(text("PRAGMA table_info(scores);"))
            existing_cols = {row[1] for row in result}

            migrations = [
                ("original_filename", "TEXT DEFAULT 'uploaded_score'"),
                ("file_type", "TEXT DEFAULT 'pdf'"),
                ("status_message", "TEXT DEFAULT ''"),
                ("measure_count", "INTEGER DEFAULT 0"),
                ("total_duration_seconds", "REAL DEFAULT 0.0"),
                ("time_signature", "TEXT DEFAULT '4/4'"),
                ("tempo_bpm", "REAL DEFAULT 120.0"),
                ("stems_metadata", "TEXT DEFAULT '{}'"),
                ("analysis_json", "TEXT DEFAULT '[]'"),
                ("audit_report", "TEXT DEFAULT '{}'"),
            ]

            for col_name, col_type in migrations:
                if col_name not in existing_cols:
                    logger.info(f"Applying SQLite migration: adding column '{col_name}' to scores table")
                    conn.execute(text(f"ALTER TABLE scores ADD COLUMN {col_name} {col_type};"))
                    conn.commit()

            # If legacy filename column exists, populate original_filename from it
            if "filename" in existing_cols:
                conn.execute(text("UPDATE scores SET original_filename = filename WHERE original_filename = 'uploaded_score' OR original_filename IS NULL;"))
                conn.commit()

            logger.info("SQLite schema verification completed successfully.")
    except Exception as e:
        logger.warning(f"Notice during SQLite schema migration check: {e}")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
