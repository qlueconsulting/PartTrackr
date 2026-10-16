import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app


def test_caroling_pdf_upload():
    fixture_path = Path(__file__).parent / "fixtures" / "Caroling_Final.pdf"
    uploaded_path = Path(
        r"C:\Users\breas\.gemini\antigravity\brain\15f23c11-bf23-46c0-9004-8ce2e5a972cd\.user_uploaded\media_1792081147290_b21cde70.pdf"
    )

    pdf_path = fixture_path if fixture_path.exists() else uploaded_path
    assert pdf_path.exists(), f"Caroling PDF not found at {pdf_path}"

    client = TestClient(app)

    with open(pdf_path, "rb") as f:
        response = client.post(
            "/api/v1/scores/upload",
            files={"file": ("Caroling_Final.pdf", f, "application/pdf")},
        )

    assert response.status_code == 200, f"Upload failed with {response.status_code}: {response.text}"
    data = response.json()

    # Verify it extracted the REAL Caroling score, NOT the 8-measure Anthem fallback
    assert data["title"] == "Caroling"
    assert "Brett Stewart" in data["composer"]
    assert data["status"] in ["ready", "completed"]
    assert data["measure_count"] == 151
    assert data["time_signature"] == "6/8"
    assert len(data["stems"]) == 11

    # Rule A5: No Piano staff in Choir PDF -> Piano stem has 0 notes
    assert data["stems"]["Piano"]["note_count"] == 0
    # All 10 choral vocal stems have the 300+ extracted notes
    for vocal_stem in ["S1", "S2", "A1", "A2", "T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
        assert data["stems"][vocal_stem]["note_count"] >= 250

    # Verify multi-measure orchestral interlude (mm. 16-92) has 0 active vocal parts
    m20 = next(m for m in data["analysis"] if m["measure_number"] == 20)
    assert m20["active_parts"] == []

    # Verify Audit Report includes AI Choral Analysis notes
    assert any("AI Analysis Provider:" in n for n in data["audit"]["notes"])


def test_mcp_endpoints():
    client = TestClient(app)
    status_res = client.get("/api/v1/mcp/status")
    assert status_res.status_code == 200
    assert status_res.json()["embedded_smufl_engine"] is True

    tools_res = client.get("/api/v1/mcp/tools")
    assert tools_res.status_code == 200
    tool_names = [t["name"] for t in tools_res.json()["tools"]]
    assert "analyze_choral_score_pdf" in tool_names
