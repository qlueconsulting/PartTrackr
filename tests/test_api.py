from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from app.database import run_sqlite_migrations

def test_health_endpoint(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["taxonomy_stems"] == 11

def test_load_sample_score_endpoint(client: TestClient):
    response = client.post("/api/v1/scores/sample/anthem")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["measure_count"] == 8
    assert len(data["stems"]) == 11
    assert "Piano" in data["stems"]
    assert "S1" in data["stems"]
    assert "B2" in data["stems"]
    assert len(data["analysis"]) == 8
    assert data["audit"]["measure_lockstep_verified"] is True
    
    score_id = data["id"]
    
    # Test GET /api/v1/scores/{score_id}
    get_res = client.get(f"/api/v1/scores/{score_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == score_id
    
    # Test GET /api/v1/scores
    list_res = client.get("/api/v1/scores")
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1
    
    # Test GET stem audio stream
    audio_res = client.get(f"/api/v1/scores/{score_id}/stems/Piano.mp3")
    assert audio_res.status_code == 200
    assert len(audio_res.content) > 0
    
    # Test GET stem notation
    mxml_res = client.get(f"/api/v1/scores/{score_id}/stems/S1.musicxml")
    assert mxml_res.status_code == 200
    assert b"score-partwise" in mxml_res.content or b"xml" in mxml_res.content

def test_upload_score_endpoint(client: TestClient, tmp_path: Path):
    from app.services.sample_scores import create_sample_unison_choral
    test_score = tmp_path / "upload_test.musicxml"
    create_sample_unison_choral(test_score)
    
    with open(test_score, "rb") as f:
        response = client.post(
            "/api/v1/scores/upload",
            files={"file": ("upload_test.musicxml", f, "application/xml")}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["measure_count"] == 6
    assert len(data["stems"]) == 11

def test_sqlite_schema_migration_handles_legacy_tables():
    """Tests that run_sqlite_migrations automatically adds missing columns to existing SQLite tables."""
    legacy_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    with legacy_engine.connect() as conn:
        # Create legacy table structure with filename VARCHAR NOT NULL without original_filename, file_type, etc.
        conn.execute(text("CREATE TABLE scores (id VARCHAR PRIMARY KEY, filename VARCHAR NOT NULL, title VARCHAR);"))
        conn.execute(text("INSERT INTO scores (id, filename, title) VALUES ('1', 'legacy_choral.pdf', 'Legacy Score');"))
        conn.commit()

    # Run migration
    run_sqlite_migrations(legacy_engine)

    # Verify original_filename and other columns now exist and are populated
    with legacy_engine.connect() as conn:
        result = conn.execute(text("SELECT id, filename, original_filename, file_type, measure_count FROM scores WHERE id='1';")).fetchone()
        assert result is not None
        assert result[1] == "legacy_choral.pdf"
        assert result[2] == "legacy_choral.pdf" # copied from legacy filename
        assert result[3] == "pdf"
        assert result[4] == 0

    # Verify inserting a new Score via ORM succeeds with both legacy filename and original_filename
    from sqlalchemy.orm import sessionmaker
    from app.models.score import Score
    Session = sessionmaker(bind=legacy_engine)
    session = Session()
    new_score = Score(
        id="2",
        title="Caroling Final",
        filename="Caroling_Final.pdf",
        original_filename="Caroling_Final.pdf",
        file_type="pdf",
        status="pending"
    )
    session.add(new_score)
    session.commit()
    fetched = session.query(Score).filter(Score.id == "2").first()
    assert fetched is not None
    assert fetched.original_filename == "Caroling_Final.pdf"
    assert fetched.filename == "Caroling_Final.pdf"
    session.close()

def test_reprocess_score_endpoint_with_hints(client: TestClient):
    # 1. Load baseline sample score (anthem has 8 measures)
    res = client.post("/api/v1/scores/sample/anthem")
    assert res.status_code == 200
    data = res.json()
    score_id = data["id"]
    assert data["measure_count"] == 8

    # 2. Reprocess score with TTBB voicing and total_measures clamped to 5
    reprocess_payload = {
        "total_measures": 5,
        "choral_voicing": "TTBB",
        "accompaniment_type": "piano",
        "tempo_bpm": 96.0
    }
    rep_res = client.post(f"/api/v1/scores/{score_id}/reprocess", json=reprocess_payload)
    assert rep_res.status_code == 200
    rep_data = rep_res.json()

    assert rep_data["status"] == "completed"
    assert rep_data["measure_count"] == 5
    assert len(rep_data["analysis"]) == 5
    assert rep_data["score_hints"]["total_measures"] == 5
    assert rep_data["score_hints"]["choral_voicing"] == "TTBB"

    # In TTBB, female stems (S1, S2, A1, A2) must have 0 notes (rests)
    assert rep_data["stems"]["S1"]["note_count"] == 0
    assert rep_data["stems"]["A1"]["note_count"] == 0
    # Male stems (T1, B1, etc.) and Piano must have active notes
    assert rep_data["stems"]["T1"]["note_count"] > 0
    assert rep_data["stems"]["Piano"]["note_count"] > 0

    # 3. Reprocess score with a_cappella hint: Piano stem must have 0 notes
    acappella_payload = {
        "total_measures": 5,
        "choral_voicing": "SATB",
        "accompaniment_type": "a_cappella"
    }
    acappella_res = client.post(f"/api/v1/scores/{score_id}/reprocess", json=acappella_payload)
    assert acappella_res.status_code == 200
    ac_data = acappella_res.json()
    assert ac_data["stems"]["Piano"]["note_count"] == 0
    assert ac_data["stems"]["Piano"]["is_active_in_score"] is False
    assert ac_data["stems"]["S1"]["note_count"] > 0

