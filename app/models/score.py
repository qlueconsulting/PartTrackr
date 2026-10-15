from datetime import datetime
import json
from sqlalchemy import Column, String, Integer, Float, DateTime, Text
from app.database import Base

class Score(Base):
    __tablename__ = "scores"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False, default="Untitled Score")
    composer = Column(String, nullable=True, default="Unknown")
    filename = Column(String, nullable=True, default="")
    original_filename = Column(String, nullable=False, default="")
    file_type = Column(String, nullable=False, default="pdf")
    status = Column(String, nullable=False, default="pending") # pending, processing, completed, failed
    status_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    measure_count = Column(Integer, default=0)
    total_duration_seconds = Column(Float, default=0.0)
    time_signature = Column(String, default="4/4")
    tempo_bpm = Column(Float, default=120.0)
    
    # JSON serialized fields
    _stems_metadata = Column("stems_metadata", Text, default="{}")
    _analysis_json = Column("analysis_json", Text, default="{}")
    _audit_report = Column("audit_report", Text, default="{}")

    @property
    def stems_metadata(self):
        if self._stems_metadata:
            return json.loads(self._stems_metadata)
        return {}

    @stems_metadata.setter
    def stems_metadata(self, val):
        self._stems_metadata = json.dumps(val)

    @property
    def analysis_json(self):
        if self._analysis_json:
            return json.loads(self._analysis_json)
        return {}

    @analysis_json.setter
    def analysis_json(self, val):
        self._analysis_json = json.dumps(val)

    @property
    def audit_report(self):
        if self._audit_report:
            return json.loads(self._audit_report)
        return {}

    @audit_report.setter
    def audit_report(self, val):
        self._audit_report = json.dumps(val)
