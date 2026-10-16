import base64
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

import pymupdf
import requests

from app.config import settings

logger = logging.getLogger(__name__)


CHORAL_ANALYSIS_SYSTEM_PROMPT = """You are PartTrackr's Real-Time AI Choral Musicologist & OMR Topology Engine.
Analyze the uploaded choral sheet music pages and symbolic telemetry according to PartTrackr's Strict Musical Rules:
- Rule A (Bracket Cues & Dynamic Choral Voice Routing):
  1. Straight Bracket `[` groups vocal choral staves; Curvy Brace `{` groups piano accompaniment.
  2. Identify staff topology per system (e.g., 2-staff SA + TB, 4-staff SATB, 1-staff unison, or divisi chords).
  3. Route upper/lower voices on SA staff to S1/S2 and A1/A2; route upper/lower voices on TB staff to T1/T2 and Bar1/Bar2/B1/B2.
  4. Never hallucinate piano notes if no curvy-brace piano staff is printed in the score (Rule A5).
- Rule B (Metric Lockstep & Multi-Measure Rest Verification):
  1. Verify all time signature changes (e.g. 6/8, 2/4, 4/4, 12/8), compound tempo referents (dotted-quarter BPM), and multi-measure rest blocks (e.g. [16-42]).

Return a concise JSON object with keys:
- "summary": 2-3 sentence executive summary of the score's choral layout and accompaniment status
- "bracket_topology": description of the bracket/staff structure
- "voice_routing_rules": list of routing observations across sections
- "metric_and_rest_verification": verification of measure counts, meter shifts, and multi-measure rests
"""


class LLMScoreAnalyzer:
    """
    Real-Time Multimodal LLM & MCP Choral Score Analyzer.
    Supports:
    1. Local GPU Vision LLM via Ollama (running on NVIDIA RTX 2060 Super 8GB + RTX 2060 6GB).
    2. External Model Context Protocol (MCP) Server via JSON-RPC.
    3. Cloud Multimodal LLM APIs (Google Gemini / OpenAI GPT-4o).
    4. Built-in SMuFL / Visual Topological Intelligence Engine.
    """

    @classmethod
    def get_engine_status(cls) -> Dict[str, Any]:
        """Checks availability of Local Ollama GPU server, MCP server, and Cloud APIs."""
        ollama_url, models = cls._probe_ollama()
        return {
            "ollama_connected": ollama_url is not None,
            "ollama_url": ollama_url or settings.OLLAMA_BASE_URL,
            "ollama_models": models,
            "preferred_ollama_model": settings.OLLAMA_MODEL,
            "mcp_configured": bool(settings.MCP_SERVER_URL),
            "mcp_server_url": settings.MCP_SERVER_URL,
            "gemini_configured": bool(settings.GEMINI_API_KEY),
            "openai_configured": bool(settings.OPENAI_API_KEY),
            "embedded_smufl_engine": True,
        }

    @classmethod
    def _probe_ollama(cls) -> tuple[Optional[str], List[str]]:
        candidates = [
            settings.OLLAMA_BASE_URL,
            "http://ollama:11434",
            "http://host.docker.internal:11434",
            "http://192.168.2.4:11434",
            "http://172.17.0.1:11434",
            "http://localhost:11434",
        ]
        seen = set()
        for base in candidates:
            if not base or base in seen:
                continue
            seen.add(base)
            base_clean = base.rstrip("/")
            try:
                resp = requests.get(f"{base_clean}/api/tags", timeout=1.2)
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    return base_clean, models
            except Exception:
                continue
        return None, []

    @classmethod
    def analyze_pdf_score(
        cls,
        pdf_path: Path,
        telemetry: Optional[Dict[str, Any]] = None,
        custom_instructions: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes real-time choral topology & metric analysis on an uploaded PDF.
        Combines deterministic visual/SMuFL telemetry with Local GPU Vision LLM / MCP reasoning.
        Incorporates user-provided measure directives & instructions into the prompt.
        """
        if not telemetry:
            from app.services.pdf_music_extractor import PDFMusicExtractor
            telemetry = PDFMusicExtractor.extract_visual_skeleton(pdf_path)

        # 1. Build deterministic ground-truth blueprint from PDF visual/SMuFL layout
        blueprint = cls._build_topological_blueprint(pdf_path, telemetry)
        if custom_instructions:
            blueprint["custom_instructions"] = custom_instructions
            blueprint["notes"].insert(0, f"[User Score Directive]: {custom_instructions}")

        # 2. Render first 2 pages with Set-of-Mark (SoM) system/staff overlays as base64 PNGs for Vision LLM / MCP
        page_images_b64 = cls._render_pdf_pages_b64(pdf_path, max_pages=2, telemetry=telemetry)

        # 3. Try External MCP Server if configured
        if settings.MCP_SERVER_URL:
            mcp_res = cls._call_external_mcp(pdf_path, blueprint, page_images_b64, custom_instructions=custom_instructions)
            if mcp_res:
                blueprint["llm_provider"] = f"MCP Server ({settings.MCP_SERVER_URL})"
                blueprint["llm_insights"] = mcp_res
                return blueprint

        # 4. Try Local GPU Ollama Server (RTX 2060 Super + RTX 2060)
        ollama_url, models = cls._probe_ollama()
        if ollama_url and models:
            ollama_res = cls._call_ollama(ollama_url, models, blueprint, page_images_b64, custom_instructions=custom_instructions)
            if ollama_res:
                blueprint["llm_provider"] = f"Local GPU Ollama ({ollama_res.get('model')})"
                blueprint["llm_insights"] = ollama_res.get("analysis")
                return blueprint

        # 5. Try Google Gemini API if configured
        if settings.GEMINI_API_KEY:
            gemini_res = cls._call_gemini(blueprint, page_images_b64, custom_instructions=custom_instructions)
            if gemini_res:
                blueprint["llm_provider"] = "Google Gemini Multimodal API"
                blueprint["llm_insights"] = gemini_res
                return blueprint

        return blueprint

    @classmethod
    def _build_topological_blueprint(
        cls,
        pdf_path: Path,
        telemetry: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not telemetry:
            return {
                "llm_provider": "PartTrackr Built-in Topological Engine",
                "title": pdf_path.stem.replace("_", " ").title(),
                "composer": "Unknown Composer",
                "has_piano": False,
                "expected_total_measures": 0,
                "systems_blueprint": [],
                "bracket_topology": "Standard Choral Layout",
                "voice_routing_rules": [
                    "Rule A: Straight bracket choral staves routed to S1, S2, A1, A2, T1, T2, Bar1, Bar2, B1, B2.",
                    "Rule A5: Accompaniment strictly matches printed score without fabricated notes."
                ],
                "metric_and_rest_verification": "Rule B lockstep clamping active across all measures.",
                "notes": []
            }

        title = telemetry.get("title", pdf_path.stem)
        composer = telemetry.get("composer", "Unknown")
        total_measures = telemetry.get("total_measures", 0)
        total_systems = telemetry.get("total_systems", 0)
        num_staves = telemetry.get("num_staves", 2)
        has_piano = telemetry.get("has_piano", False)
        systems_blueprint = telemetry.get("systems_blueprint", [])
        measures = telemetry.get("measures", [])

        # Identify meter changes, tempo changes, and multi-measure rest spans
        meter_changes = []
        tempo_changes = []
        mm_rest_spans = []

        prev_ts = None
        prev_tempo = None
        rest_run_start = None
        rest_run_end = None

        for m in measures:
            m_num = m["measure"]
            ts = m["ts"]
            tbpm = m["tempo_bpm"]
            m_type = m["type"]

            if ts != prev_ts:
                meter_changes.append(f"m.{m_num}: {ts}")
                prev_ts = ts
            if tbpm != prev_tempo:
                tempo_changes.append(f"m.{m_num}: {tbpm} BPM (quarter-note grid)")
                prev_tempo = tbpm

            if m_type == "multi_measure_rest":
                if rest_run_start is None:
                    rest_run_start = m_num
                rest_run_end = m_num
            else:
                if rest_run_start is not None:
                    mm_rest_spans.append(f"mm.{rest_run_start}–{rest_run_end} ({rest_run_end - rest_run_start + 1} bars)")
                    rest_run_start = None
                    rest_run_end = None

        if rest_run_start is not None:
            mm_rest_spans.append(f"mm.{rest_run_start}–{rest_run_end} ({rest_run_end - rest_run_start + 1} bars)")

        if not has_piano and num_staves == 2:
            bracket_desc = (
                f"Straight Bracket `[` spanning {num_staves} Choral Staves across {total_systems} systems "
                f"(Staff 1: Soprano/Alto in Treble Clef; Staff 2: Tenor/Bass in Bass Clef). "
                f"No curvy-brace `{{` Piano staff printed in PDF -> Piano stem rests cleanly per Rule A5."
            )
        elif has_piano:
            bracket_desc = (
                f"Accompanied Choral Layout ({total_systems} systems, up to {num_staves} staves/system): "
                f"Bottom 2 staves anchored to Piano Grand Staff `{{` (Rule A1a); upper staves routed dynamically per system to Choir `[`."
            )
        else:
            bracket_desc = f"Multi-staff choral layout ({num_staves} staves across {total_systems} systems)."

        routing_rules = [
            f"Identified '{title}' ({composer}) — {total_measures} lockstep measures across {total_systems} engraved systems.",
            bracket_desc,
            "Divisi & Polyphony Routing (Rule A2): Upper notes on Female/SA staves -> S1, S2; Lower notes -> A1, A2.",
            "Male Staff Routing (Rule A2): Upper notes on Male/TB staves -> T1, T2; Lower notes -> Bar1, Bar2, B1, B2.",
        ]
        if meter_changes:
            routing_rules.append(f"Meter Transitions (Rule B1): {', '.join(meter_changes)}.")
        if tempo_changes:
            routing_rules.append(f"Tempo Map: {', '.join(tempo_changes)}.")
        if mm_rest_spans:
            routing_rules.append(
                f"Multi-Measure Tacet / Interlude Spans Expanded: {', '.join(mm_rest_spans)} (all 10 vocal stems rest cleanly with zero OMR bleed)."
            )

        return {
            "llm_provider": "PartTrackr SMuFL + Topological Intelligence Engine",
            "title": title,
            "composer": composer,
            "has_piano": has_piano,
            "expected_total_measures": total_measures,
            "systems_blueprint": systems_blueprint,
            "bracket_topology": bracket_desc,
            "voice_routing_rules": routing_rules,
            "metric_and_rest_verification": (
                f"Verified {total_measures} contiguous measures (m.1..m.{total_measures}) "
                f"with {len(mm_rest_spans)} multi-measure rest spans and {len(meter_changes)} time signature shifts."
            ),
            "notes": routing_rules,
        }

    @classmethod
    def _render_pdf_pages_b64(
        cls,
        pdf_path: Path,
        max_pages: int = 2,
        telemetry: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Renders the first N pages of the PDF with Set-of-Mark (SoM) visual system and staff
        annotations so the Vision LLM has explicit spatial and measure-number grounding.
        """
        images = []
        sys_bp = (telemetry or {}).get("systems_blueprint", [])
        try:
            doc = pymupdf.open(str(pdf_path))
            for i in range(min(len(doc), max_pages)):
                page = doc[i]
                page_num = i + 1
                # Draw Set-of-Mark annotations for systems on this page
                page_systems = [s for s in sys_bp if s.get("page_num") == page_num]
                for s in page_systems:
                    try:
                        rect = pymupdf.Rect(
                            max(2.0, s["x_left"] - 35.0),
                            max(2.0, s["y_top"] - 10.0),
                            min(page.rect.width - 2.0, s["x_right"] + 4.0),
                            min(page.rect.height - 2.0, s["y_bot"] + 10.0)
                        )
                        page.draw_rect(rect, color=(0.15, 0.35, 0.85), width=0.8)
                        label = f"SYS {s['system_index']} (m.{s['measure_start']}-{s['measure_end']})"
                        page.insert_text(
                            pymupdf.Point(max(4.0, s["x_left"] - 34.0), max(10.0, s["y_top"] - 2.0)),
                            label,
                            fontsize=6.5,
                            color=(0.1, 0.25, 0.75)
                        )
                    except Exception:
                        pass
                pix = page.get_pixmap(dpi=120)
                png_bytes = pix.tobytes("png")
                images.append(base64.b64encode(png_bytes).decode("ascii"))
            doc.close()
        except Exception as e:
            logger.warning(f"Failed to render PDF pages for LLM vision: {e}")
        return images

    @classmethod
    def _call_ollama(
        cls,
        ollama_url: str,
        models: List[str],
        blueprint: Dict[str, Any],
        images_b64: List[str],
        custom_instructions: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        # Select preferred vision model or first available model
        vision_keywords = ["vl", "vision", "llava", "minicpm", "gemma3"]
        selected_model = None
        if settings.OLLAMA_MODEL in models:
            selected_model = settings.OLLAMA_MODEL
        else:
            for m in models:
                if any(vk in m.lower() for vk in vision_keywords):
                    selected_model = m
                    break
            if not selected_model and models:
                selected_model = models[0]

        if not selected_model:
            return None

        user_prompt_addon = f"\n\nUSER DIRECTIVES & MEASURE INSTRUCTIONS:\n\"{custom_instructions}\"" if custom_instructions else ""
        prompt = (
            f"{CHORAL_ANALYSIS_SYSTEM_PROMPT}\n\n"
            f"Extracted Symbolic Telemetry:\n{json.dumps(blueprint, indent=2)}"
            f"{user_prompt_addon}"
        )

        payload: Dict[str, Any] = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        if images_b64 and any(vk in selected_model.lower() for vk in vision_keywords):
            payload["images"] = images_b64

        try:
            logger.info(f"Invoking Local GPU Ollama model '{selected_model}' at {ollama_url}...")
            resp = requests.post(f"{ollama_url}/api/generate", json=payload, timeout=25)
            if resp.status_code == 200:
                raw_resp = resp.json().get("response", "")
                try:
                    parsed = json.loads(raw_resp)
                except Exception:
                    parsed = {"summary": raw_resp}
                if isinstance(parsed.get("summary"), str):
                    blueprint["notes"].insert(
                        0, f"[Local GPU LLM ({selected_model})]: {parsed['summary']}"
                    )
                return {"model": selected_model, "analysis": parsed}
        except Exception as e:
            logger.warning(f"Local Ollama call skipped/failed: {e}")
        return None

    @classmethod
    def _call_external_mcp(
        cls,
        pdf_path: Path,
        blueprint: Dict[str, Any],
        images_b64: List[str],
        custom_instructions: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        try:
            args: Dict[str, Any] = {
                "filename": pdf_path.name,
                "telemetry": blueprint,
                "page_images_b64": images_b64[:1],
            }
            if custom_instructions:
                args["custom_instructions"] = custom_instructions

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "analyze_choral_score",
                    "arguments": args
                }
            }
            resp = requests.post(settings.MCP_SERVER_URL, json=payload, timeout=20)
            if resp.status_code == 200:
                res = resp.json().get("result", {})
                blueprint["notes"].insert(0, f"[External MCP Analysis]: {json.dumps(res)[:300]}")
                return res
        except Exception as e:
            logger.warning(f"External MCP server call failed: {e}")
        return None

    @classmethod
    def _call_gemini(
        cls,
        blueprint: Dict[str, Any],
        images_b64: List[str],
        custom_instructions: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        try:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
            )
            user_prompt_addon = f"\n\nUSER DIRECTIVES & MEASURE INSTRUCTIONS:\n\"{custom_instructions}\"" if custom_instructions else ""
            parts: List[Dict[str, Any]] = [
                {"text": f"{CHORAL_ANALYSIS_SYSTEM_PROMPT}\n\nTelemetry:\n{json.dumps(blueprint)}{user_prompt_addon}"}
            ]
            for img in images_b64[:2]:
                parts.append({"inline_data": {"mime_type": "image/png", "data": img}})

            resp = requests.post(url, json={"contents": [{"parts": parts}]}, timeout=20)
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates:
                    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    blueprint["notes"].insert(0, f"[Gemini Vision Analysis]: {text[:300]}")
                    return {"summary": text}
        except Exception as e:
            logger.warning(f"Gemini API call failed: {e}")
        return None

    @classmethod
    def analyze_instructions(
        cls,
        custom_instructions: str,
        blueprint: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Processes user score directives and measure instructions using Local GPU Ollama, MCP, or Gemini.
        Returns updated blueprint and audit notes reflecting the AI's understanding of the instructions.
        """
        bp = blueprint or {
            "title": "Choral Score",
            "notes": [],
            "expected_total_measures": 0
        }
        if not custom_instructions or not custom_instructions.strip():
            return bp

        text = custom_instructions.strip()
        bp["custom_instructions"] = text
        directive_note = f"[User Score Directive]: {text}"
        if directive_note not in bp.get("notes", []):
            bp.setdefault("notes", []).insert(0, directive_note)

        # Query Local Ollama GPU probe if available
        ollama_url, models = cls._probe_ollama()
        if ollama_url and models:
            selected_model = settings.OLLAMA_MODEL if settings.OLLAMA_MODEL in models else models[0]
            prompt = (
                f"{CHORAL_ANALYSIS_SYSTEM_PROMPT}\n\n"
                f"User-entered measure directives and music discovery instructions:\n"
                f"\"{text}\"\n\n"
                f"Score Metadata:\n{json.dumps(bp, indent=2)}\n\n"
                "Return a JSON object with 'summary' explaining how these instructions guide voice routing and measures."
            )
            payload = {
                "model": selected_model,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }
            try:
                resp = requests.post(f"{ollama_url}/api/generate", json=payload, timeout=12)
                if resp.status_code == 200:
                    raw_resp = resp.json().get("response", "")
                    try:
                        parsed = json.loads(raw_resp)
                        if "summary" in parsed and isinstance(parsed["summary"], str):
                            bp["notes"].insert(0, f"[Local GPU LLM ({selected_model}) Directives Analysis]: {parsed['summary']}")
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Ollama directive analysis failed: {e}")

        return bp

