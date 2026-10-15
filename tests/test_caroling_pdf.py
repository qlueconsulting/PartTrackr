import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

def test_caroling_pdf_upload():
    # Prefer test fixtures copy, fallback to user uploaded path
    fixture_path = Path(__file__).parent / "fixtures" / "Caroling_Final.pdf"
    uploaded_path = Path(r"C:\Users\breas\.gemini\antigravity\brain\15f23c11-bf23-46c0-9004-8ce2e5a972cd\.user_uploaded\media_1792081147290_b21cde70.pdf")

    pdf_path = fixture_path if fixture_path.exists() else uploaded_path
    assert pdf_path.exists(), f"Caroling PDF not found at {pdf_path}"

    client = TestClient(app)
    
    with open(pdf_path, "rb") as f:
        response = client.post(
            "/api/v1/scores/upload",
            files={"file": ("Caroling_Final.pdf", f, "application/pdf")}
        )

    assert response.status_code == 200, f"Upload failed with {response.status_code}: {response.text}"
    data = response.json()
    assert data["title"] is not None
    assert data["status"] in ["ready", "completed"]
    assert "Piano" in data["stems"]
    assert "S1" in data["stems"]
    assert "B2" in data["stems"]
    assert len(data["stems"]) == 11
    assert data["measure_count"] > 0
    print("Test passed! Returned score:", data["id"], data["title"], "measures:", data["measure_count"])

if __name__ == "__main__":
    test_caroling_pdf_upload()
