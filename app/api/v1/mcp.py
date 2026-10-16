from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.llm_analyzer import LLMScoreAnalyzer
from app.services.pdf_music_extractor import PDFMusicExtractor

router = APIRouter()


class MCPCallRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[int | str] = 1
    method: str = "tools/call"
    params: Dict[str, Any] = {}


@router.get("/status")
async def get_ai_mcp_status():
    """Returns real-time status of Local GPU Ollama, External MCP Server, and SMuFL Vector Engine."""
    return LLMScoreAnalyzer.get_engine_status()


@router.get("/tools")
async def list_mcp_tools():
    """Exposes PartTrackr's choral sheet music intelligence tools via Model Context Protocol (MCP)."""
    return {
        "tools": [
            {
                "name": "analyze_choral_score_pdf",
                "description": (
                    "Extracts SMuFL vector music glyphs, 5-line staff geometries, barlines, "
                    "multi-measure rests, and runs real-time AI choral voice routing analysis on a PDF."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pdf_path": {"type": "string", "description": "Path to the choral PDF file on server"}
                    },
                    "required": ["pdf_path"]
                }
            },
            {
                "name": "get_ai_engine_status",
                "description": "Checks connection to Local GPU Ollama server, MCP server, and SMuFL engine.",
                "inputSchema": {"type": "object", "properties": {}}
            }
        ]
    }


@router.post("/call")
async def call_mcp_tool(req: MCPCallRequest):
    """JSON-RPC 2.0 MCP endpoint for invoking PartTrackr sheet music analysis tools."""
    if req.method == "tools/list":
        return {"jsonrpc": "2.0", "id": req.id, "result": await list_mcp_tools()}

    tool_name = req.params.get("name")
    args = req.params.get("arguments", {})

    if tool_name == "get_ai_engine_status":
        return {"jsonrpc": "2.0", "id": req.id, "result": LLMScoreAnalyzer.get_engine_status()}

    elif tool_name == "analyze_choral_score_pdf":
        pdf_path = Path(args.get("pdf_path", ""))
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail=f"PDF not found at {pdf_path}")
        out_xml = pdf_path.parent / f"{pdf_path.stem}_mcp.musicxml"
        _, telemetry = PDFMusicExtractor.extract_to_musicxml(pdf_path, out_xml)
        blueprint = LLMScoreAnalyzer.analyze_pdf_score(pdf_path, telemetry)
        return {
            "jsonrpc": "2.0",
            "id": req.id,
            "result": {
                "musicxml_path": str(out_xml),
                "telemetry": telemetry,
                "blueprint": blueprint
            }
        }

    raise HTTPException(status_code=400, detail=f"Unknown MCP tool: {tool_name}")
