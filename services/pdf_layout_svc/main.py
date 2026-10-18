import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from services.pdf_layout_svc.layout_engine import PDFLayoutEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pdf_layout_svc")

app = FastAPI(
    title="PartTrackr - PDF Layout Service",
    version="1.0.0",
    description="300 DPI PDF rasterization, staff bounding box detection, and crop generator",
)


class LayoutRequest(BaseModel):
    job_id: str
    pdf_path: str
    output_dir: str
    dpi: int = Field(300, description="DPI for page rendering and crops")


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "pdf-layout-svc", "port": 8006}


@app.post("/api/v1/layout/process")
def process_layout(req: LayoutRequest) -> Dict[str, Any]:
    pdf_file = Path(req.pdf_path)
    out_dir = Path(req.output_dir)

    if not pdf_file.exists():
        raise HTTPException(status_code=404, detail=f"PDF file not found at {req.pdf_path}")

    try:
        logger.info(f"Processing PDF layout for job {req.job_id}: {pdf_file.name} at {req.dpi} DPI")
        result = PDFLayoutEngine.process_pdf(pdf_file, out_dir, dpi=req.dpi)
        result["job_id"] = req.job_id
        return result
    except Exception as e:
        logger.exception(f"Layout processing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Layout processing error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8006)
