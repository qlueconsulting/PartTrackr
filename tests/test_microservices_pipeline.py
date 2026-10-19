import pytest
from pathlib import Path
import json

from common.taxonomy import CANONICAL_11_PARTS
from common.cism_schema import ScoreCISM
from services.pdf_layout_svc.layout_engine import PDFLayoutEngine
from services.omr_ai_svc.vector_smufl_extractor import VectorSMuFLExtractor
from services.omr_ai_svc.vision_llm_adapter import VisionLLMAdapter
from services.voice_router_svc.router_engine import VoiceRouterEngine
from services.decoder_xml_svc.xml_compiler import XMLCompiler
from services.decoder_xml_svc.midi_generator import MIDIGenerator


def test_microservices_end_to_end(tmp_path):
    pdf_path = Path("tests/fixtures/Caroling_Final.pdf")
    assert pdf_path.exists(), "Test PDF Caroling_Final.pdf not found"

    # Step 1: Layout Service Engine
    layout_out_dir = tmp_path / "layout"
    layout_data = PDFLayoutEngine.process_pdf(pdf_path, layout_out_dir, dpi=150)
    
    assert layout_data["page_count"] >= 1
    assert layout_data["total_systems"] >= 1
    assert layout_data["total_measures"] >= 1
    assert (layout_out_dir / "page_1.png").exists()
    assert (layout_out_dir / "crops" / "system_1.png").exists()

    # Step 2: OMR AI Service Engine
    if VectorSMuFLExtractor.can_extract(pdf_path):
        raw_cism = VectorSMuFLExtractor.extract_cism(pdf_path, layout_data)
        assert raw_cism.metadata.get("omr_engine") == "VectorSMuFL"
    else:
        raw_cism = VisionLLMAdapter.extract_cism_from_crops(layout_data)
        assert raw_cism.metadata.get("omr_engine") == "VisionLLM"

    assert raw_cism.total_measures >= 1
    assert len(raw_cism.systems) == layout_data["total_systems"]

    # Step 3: Voice Router Service Engine (11 Canonical Tracks)
    routed_cism = VoiceRouterEngine.route_score(raw_cism)
    assert len(routed_cism.systems) >= 1

    first_m = routed_cism.systems[0].measures[0]
    for p_name in CANONICAL_11_PARTS:
        assert p_name in first_m.tracks, f"Missing canonical track {p_name} in routed measure"
        track_obj = first_m.tracks[p_name]
        assert len(track_obj.elements) >= 1

    # Step 4: Decoder XML Service Engine
    compiled_dir = tmp_path / "compiled"
    main_xml_path, stem_xml_paths, measure_summary = XMLCompiler.compile_score(routed_cism, compiled_dir)
    assert main_xml_path.exists()
    assert len(stem_xml_paths) == 11
    for p_name in CANONICAL_11_PARTS:
        assert stem_xml_paths[p_name].exists()

    # Step 5: MIDI & Sync Map Compilation
    main_midi_path, stem_midi_paths, sync_map_path = MIDIGenerator.compile_midi_and_sync_map(routed_cism, compiled_dir)
    assert main_midi_path.exists()
    assert sync_map_path.exists()
    assert len(stem_midi_paths) == 11

    with open(sync_map_path, "r", encoding="utf-8") as f:
        sync_map_data = json.load(f)
    assert len(sync_map_data["measures"]) == len(measure_summary)


def test_preflight_analysis():
    pdf_path = Path("tests/fixtures/Caroling_Final.pdf")
    assert pdf_path.exists()

    preflight = PDFLayoutEngine.preflight_analysis(pdf_path)
    assert preflight["title"] == "Caroling"
    assert preflight["page_count"] == 5
    assert preflight["time_signature"] == "6/8"
    assert preflight["tempo_bpm"] == 92.0
    assert preflight["choral_voicing"] == "SA_TB"
    assert preflight["has_piano"] is False
    assert "part_layout_summary" in preflight
    assert "suggested_custom_instructions" in preflight
    assert "compound duple in 2 feel" in preflight["suggested_custom_instructions"]
    assert "Soprano" in preflight["suggested_custom_instructions"]


def test_gateway_preflight_and_reprocess_endpoints():
    from fastapi.testclient import TestClient
    from services.gateway_svc.main import app

    client = TestClient(app)
    pdf_path = Path("tests/fixtures/Caroling_Final.pdf")
    assert pdf_path.exists()

    # 1. Upload score
    with open(pdf_path, "rb") as f:
        resp = client.post("/api/v1/jobs/upload", files={"file": ("Caroling_Final.pdf", f, "application/pdf")})
    assert resp.status_code == 200
    upload_data = resp.json()
    job_id = upload_data["job_id"]
    assert "preflight" in upload_data
    assert upload_data["preflight"]["time_signature"] == "6/8"
    assert "suggested_custom_instructions" in upload_data["preflight"]

    # 2. Query preflight endpoint
    pre_resp = client.get(f"/api/v1/jobs/{job_id}/preflight")
    assert pre_resp.status_code == 200
    pre_data = pre_resp.json()
    assert pre_data["job_id"] == job_id
    assert pre_data["time_signature"] == "6/8"
    assert pre_data["tempo_bpm"] == 92.0

    # 3. Reprocess score with user AI hints
    reprocess_payload = {
        "time_signature": "6/8",
        "tempo_bpm": 96.0,
        "choral_voicing": "SATB",
        "accompaniment_type": "piano",
        "custom_instructions": "Bars 1-4 are piano prelude; Soprano divisi on refrain"
    }
    rep_resp = client.post(f"/api/v1/jobs/{job_id}/reprocess", json=reprocess_payload)
    assert rep_resp.status_code == 200
    rep_data = rep_resp.json()
    assert rep_data["job_id"] == job_id
    assert rep_data["status"] == "pending"
    assert rep_data["score_hints"]["custom_instructions"] == "Bars 1-4 are piano prelude; Soprano divisi on refrain"

    # 4. Query job history list (last 10) and verify AI hints are preserved
    history_resp = client.get("/api/v1/jobs?limit=10")
    assert history_resp.status_code == 200
    history_jobs = history_resp.json()
    assert len(history_jobs) >= 1
    target = next((j for j in history_jobs if j["job_id"] == job_id), None)
    assert target["score_hints"]["custom_instructions"] == "Bars 1-4 are piano prelude; Soprano divisi on refrain"


def test_reconcile_total_measures_ground_truth(tmp_path):
    from common.lockstep_utils import reconcile_cism_measures
    from common.cism_schema import SystemData, MeasureData, BoundingBox, TrackData, NoteElement

    # Build synthetic CISM with 8 measures across 2 systems
    sys1 = SystemData(
        system_index=0,
        page_num=1,
        bounding_box=BoundingBox(x=0, y=0, w=600, h=200),
        measures=[MeasureData(measure_number=i+1, time_signature="4/4", tempo_bpm=120) for i in range(4)]
    )
    sys2 = SystemData(
        system_index=1,
        page_num=1,
        bounding_box=BoundingBox(x=0, y=200, w=600, h=200),
        measures=[MeasureData(measure_number=i+5, time_signature="4/4", tempo_bpm=120) for i in range(4)]
    )
    cism = ScoreCISM(
        score_id="test_reconcile",
        title="Test Score",
        composer="Composer",
        total_systems=2,
        total_measures=8,
        systems=[sys1, sys2]
    )

    # 1. Truncate from 8 to 5 measures
    clamped = reconcile_cism_measures(cism.model_copy(deep=True), target_total_measures=5)
    assert clamped.total_measures == 5
    assert len(clamped.all_measures()) == 5
    assert [m.measure_number for m in clamped.all_measures()] == [1, 2, 3, 4, 5]

    # 2. Pad from 8 to 12 measures
    padded = reconcile_cism_measures(cism.model_copy(deep=True), target_total_measures=12, target_time_signature="3/4", target_tempo_bpm=100.0)
    assert padded.total_measures == 12
    assert len(padded.all_measures()) == 12
    assert [m.measure_number for m in padded.all_measures()] == list(range(1, 13))
    last_m = padded.all_measures()[-1]
    assert last_m.time_signature == "3/4"
    assert last_m.tempo_bpm == 100.0
    for p in CANONICAL_11_PARTS:
        assert p in last_m.tracks
        assert len(last_m.tracks[p].elements) == 1
        assert last_m.tracks[p].elements[0].is_rest is True

    # 3. Route with score_hints enforcing total_measures=6
    routed = VoiceRouterEngine.route_score(
        cism,
        score_hints={"total_measures": 6, "accompaniment_type": "piano", "time_signature": "4/4"}
    )
    assert routed.total_measures == 6
    assert len(routed.all_measures()) == 6
    assert routed.has_piano is True

    # 4. Decoder XML compile with score_hints
    compiled_dir = tmp_path / "compiled_hints"
    main_xml, stems, summary = XMLCompiler.compile_score(routed, compiled_dir)
    assert len(summary) == 6
    assert summary[-1]["measure_number"] == 6

    main_midi, stem_midis, sync_map_path = MIDIGenerator.compile_midi_and_sync_map(routed, compiled_dir)
    with open(sync_map_path, "r", encoding="utf-8") as f:
        sync = json.load(f)
    assert sync["total_measures"] == 6
    assert len(sync["measures"]) == 6


