from pathlib import Path
import pytest
from fastapi.testclient import TestClient

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
