from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """Initializes tables and migrates any missing columns safely."""
    Base.metadata.create_all(bind=engine)
    if "sqlite" in settings.DATABASE_URL:
        with engine.connect() as conn:
            for col_def in [
                ("error_traceback", "TEXT"),
                ("processing_logs", "JSON"),
                ("measure_analysis", "JSON"),
                ("score_profile", "JSON"),
            ]:
                try:
                    conn.execute(text(f"ALTER TABLE scores ADD COLUMN {col_def[0]} {col_def[1]}"))
                    conn.commit()
                except Exception:
                    pass  # Column already exists


def get_db():
    """Dependency that provides an independent database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
