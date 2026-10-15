from pathlib import Path
import pytest

from app.services.sample_scores import create_sample_satb_with_piano
from app.services.notation_processor import NotationProcessor
from app.services.audit_service import ScoreAuditService

def test_score_audit_report(tmp_path: Path):
    score_path = tmp_path / "anthem.musicxml"
    create_sample_satb_with_piano(score_path)
    
    proc = NotationProcessor(score_path)
    stems, analysis = proc.extract_all_stems()
    
    audit = ScoreAuditService.audit_score(stems, analysis, proc.raw_score)
    
    assert audit.overall_match_integrity_pct >= 95.0
    assert audit.accompaniment_continuity is True
    assert audit.measure_lockstep_verified is True
    assert audit.interlude_cleanliness_pct >= 99.0
    assert audit.measure_count == 8
    assert audit.time_drift_max_seconds <= 0.01
    assert len(audit.checks) == 5
    for c in audit.checks:
        assert c.passed is True
