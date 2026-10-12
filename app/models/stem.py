import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.database import Base


class Stem(Base):
    __tablename__ = "stems"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    score_id = Column(String(36), ForeignKey("scores.id", ondelete="CASCADE"), nullable=False)
    part_name = Column(String(100), nullable=False)  # e.g., "Tenor I", "Piano Score"
    part_key = Column(String(20), nullable=False)   # e.g., "T1", "Piano", "S1", "A1", "B1"
    is_accompaniment = Column(Boolean, default=False)
    original_part_name = Column(String(150), nullable=True)
    midi_path = Column(String(500), nullable=False)
    audio_path = Column(String(500), nullable=False)
    duration_seconds = Column(Float, default=0.0)
    pitch_range = Column(String(50), nullable=True)  # e.g. "C3 - A4"
    measure_count = Column(Integer, default=0)
    note_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    score = relationship("Score", back_populates="stems")
