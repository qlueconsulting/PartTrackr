import io
from pathlib import Path
import music21 as m21
import pytest
from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "PartTrackr"


def test_serve_index_html(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "PartTrackr" in response.text


def test_score_upload_and_pipeline(client: TestClient, tmp_path):
    """Test score upload, background pipeline execution, and audio stem retrieval."""
    # Create simple MusicXML content
    score = m21.stream.Score()
    part = m21.stream.Part()
    part.partName = "Soprano I"
    m = m21.stream.Measure(number=1)
    m.append(m21.note.Note("A4", quarterLength=4))
    part.append(m)
    score.append(part)

    xml_path = tmp_path / "test_soprano.musicxml"
    score.write("musicxml", fp=str(xml_path))

    with open(xml_path, "rb") as f:
        file_bytes = f.read()

    # Upload file
    response = client.post(
        "/api/v1/scores/upload",
        files={"file": ("test_soprano.musicxml", io.BytesIO(file_bytes), "application/xml")},
    )
    assert response.status_code == 202
    score_data = response.json()
    assert score_data["id"] is not None
    assert score_data["filename"] == "test_soprano.musicxml"
    score_id = score_data["id"]

    # In TestClient, BackgroundTasks run during the request,
    # so by the time we query, pipeline should have processed.
    detail_res = client.get(f"/api/v1/scores/{score_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["status"] == "ready"
    assert len(detail["stems"]) == 11
    assert "measure_analysis" in detail
    assert detail["measure_analysis"]["total_measures"] >= 1

    stem = next(s for s in detail["stems"] if s["part_key"] == "S1")
    assert stem["part_key"] == "S1"
    assert stem["audio_url"] is not None
    assert stem["midi_url"] is not None

    # Test Audio streaming endpoint
    audio_res = client.get(f"/api/v1/scores/{score_id}/stems/{stem['id']}/audio")
    assert audio_res.status_code == 200
    assert audio_res.headers["content-type"] in ["audio/wav", "audio/mpeg"]
    assert len(audio_res.content) > 0

    # Test MIDI download endpoint
    midi_res = client.get(f"/api/v1/scores/{score_id}/stems/{stem['id']}/midi")
    assert midi_res.status_code == 200
    assert midi_res.headers["content-type"] == "audio/midi"
    assert len(midi_res.content) > 0

    # Test List Scores
    list_res = client.get("/api/v1/scores")
    assert list_res.status_code == 200
    assert list_res.json()["total"] >= 1

    # Test Delete Score
    del_res = client.delete(f"/api/v1/scores/{score_id}")
    assert del_res.status_code == 204

    # Verify 404 after deletion
    after_del = client.get(f"/api/v1/scores/{score_id}")
    assert after_del.status_code == 404


def test_load_sample_score(client: TestClient):
    """Test loading built-in Bach SATB + Piano sample score."""
    response = client.post("/api/v1/scores/load-sample")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert len(data["stems"]) == 11  # All 11 parts guaranteed
    assert "measure_analysis" in data
    assert data["measure_analysis"]["total_measures"] >= 1

    stem_keys = [s["part_key"] for s in data["stems"]]
    for k in ["Piano", "S1", "S2", "A1", "A2", "T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
        assert k in stem_keys

    # Verify processing_logs are recorded
    assert "processing_logs" in data
    assert len(data["processing_logs"]) > 0
    # Check log structure
    first_log = data["processing_logs"][0]
    assert "timestamp" in first_log
    assert "stage" in first_log
    assert "level" in first_log
    assert "message" in first_log


def test_score_reprocess_endpoint(client: TestClient):
    """Test triggering reprocess endpoint for an existing score."""
    # Seed score
    sample_res = client.post("/api/v1/scores/load-sample")
    assert sample_res.status_code == 200
    score_id = sample_res.json()["id"]

    # Trigger reprocess
    reprocess_res = client.post(f"/api/v1/scores/{score_id}/reprocess")
    assert reprocess_res.status_code == 200
    reprocess_data = reprocess_res.json()
    assert reprocess_data["id"] == score_id
    assert reprocess_data["status"] == "queued"

    # Query updated score after background task executes
    detail_res = client.get(f"/api/v1/scores/{score_id}")
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["status"] == "ready"
    assert len(detail_data["processing_logs"]) > 0

