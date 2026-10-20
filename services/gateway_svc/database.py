from datetime import datetime
import json
from pathlib import Path
from typing import Optional, Dict, Any
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Text, JSON
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(64), primary_key=True, index=True)
    status = Column(String(32), default="pending")  # pending, layout, omr, routing, decoding, completed, failed
    stage_message = Column(String(256), default="Job created")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    original_filename = Column(String(256))
    pdf_path = Column(String(512))
    title = Column(String(256), default="Choral Score")
    composer = Column(String(256), default="Unknown Composer")
    page_count = Column(Integer, default=1)
    total_measures = Column(Integer, default=0)
    total_duration_seconds = Column(Float, default=0.0)

    # Serialized intermediate pipeline results
    layout_data = Column(JSON, nullable=True)
    raw_cism = Column(JSON, nullable=True)
    routed_cism = Column(JSON, nullable=True)
    decoder_result = Column(JSON, nullable=True)
    overrides = Column(JSON, nullable=True)
    score_hints = Column(JSON, nullable=True)
    verification_report = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)


def init_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    # Ensure score_hints & verification_report columns exist in existing DBs
    try:
        with engine.connect() as conn:
            from sqlalchemy import text
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs);")).fetchall()]
            if "score_hints" not in cols:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN score_hints JSON;"))
                conn.commit()
            if "verification_report" not in cols:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN verification_report JSON;"))
                conn.commit()
    except Exception:
        pass
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)

