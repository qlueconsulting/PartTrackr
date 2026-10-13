import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, JSON
from sqlalchemy.orm import relationship
from app.database import Base


class Score(Base):
    __tablename__ = "scores"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False, default="Untitled Score")
    composer = Column(String(255), nullable=True)
    status = Column(
        String(50),
        nullable=False,
        default="queued",
        comment="queued, processing_omr, parsing, synthesizing, ready, failed",
    )
    detected_parts = Column(JSON, default=list)  # List of part metadata
    error_message = Column(Text, nullable=True)
    error_traceback = Column(Text, nullable=True)
    processing_logs = Column(JSON, default=list)  # List of log message objects
    measure_analysis = Column(JSON, default=dict)  # Detailed measure analysis, entrances, rests
    score_profile = Column(JSON, default=dict)  # Discovered / learned dynamic choral structure profile
    original_path = Column(String(500), nullable=True)
    xml_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    stems = relationship("Stem", back_populates="score", cascade="all, delete-orphan", order_by="Stem.part_key")
