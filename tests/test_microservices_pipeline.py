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
    main_xml_path, piano_xml_path, vocals_xml_path, stem_xml_paths, measure_summary = XMLCompiler.compile_score(routed_cism, compiled_dir)
    assert main_xml_path.exists()
    assert piano_xml_path.exists()
    assert vocals_xml_path.exists()
    assert len(stem_xml_paths) == 11
    for p_name in CANONICAL_11_PARTS:
        assert stem_xml_paths[p_name].exists()

    # Step 5: MIDI & Sync Map Compilation
    main_midi_path, piano_midi_path, vocals_midi_path, stem_midi_paths, sync_map_path = MIDIGenerator.compile_midi_and_sync_map(routed_cism, compiled_dir)
    assert main_midi_path.exists()
    assert piano_midi_path.exists()
    assert vocals_midi_path.exists()
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
    main_xml, piano_xml, vocals_xml, stems, summary = XMLCompiler.compile_score(routed, compiled_dir)
    assert len(summary) == 6
    assert summary[-1]["measure_number"] == 6
    assert main_xml.exists()
    assert piano_xml.exists()
    assert vocals_xml.exists()

    main_midi, piano_midi, vocals_midi, stem_midis, sync_map_path = MIDIGenerator.compile_midi_and_sync_map(routed, compiled_dir)
    assert main_midi.exists()
    assert piano_midi.exists()
    assert vocals_midi.exists()
    with open(sync_map_path, "r", encoding="utf-8") as f:
        sync = json.load(f)
    assert sync["total_measures"] == 6
    assert len(sync["measures"]) == 6


@pytest.mark.anyio
async def test_orchestrator_in_process_fallback_when_dns_fails(tmp_path, monkeypatch):
    """Verify that when microservices HTTP endpoints fail DNS resolution, orchestrator falls back in-process."""
    from services.gateway_svc.database import Job
    from services.gateway_svc.main import SessionFactory
    from services.gateway_svc.orchestrator import PipelineOrchestrator
    import services.gateway_svc.orchestrator as orch_mod

    # Force invalid hostnames that trigger DNS resolution failure
    monkeypatch.setattr(orch_mod, "LAYOUT_SVC_URL", "http://non-existent-layout-svc.invalid:8006")
    monkeypatch.setattr(orch_mod, "OMR_SVC_URL", "http://non-existent-omr-svc.invalid:8007")
    monkeypatch.setattr(orch_mod, "ROUTER_SVC_URL", "http://non-existent-router-svc.invalid:8008")
    monkeypatch.setattr(orch_mod, "DECODER_SVC_URL", "http://non-existent-decoder-svc.invalid:8009")

    # Fast retries for testing
    orig_post = orch_mod._post_with_retry_and_fallback
    async def fast_post(endpoint_name, primary_url, path, payload, fallback_urls=None, max_retries=1, timeout_sec=600.0):
        return await orig_post(endpoint_name, primary_url, path, payload, fallback_urls=[], max_retries=1, timeout_sec=1.0)
    monkeypatch.setattr(orch_mod, "_post_with_retry_and_fallback", fast_post)

    db = SessionFactory()
    job_id = "test_dns_fallback"
    existing = db.query(Job).filter(Job.id == job_id).first()
    if existing:
        db.delete(existing)
        db.commit()

    pdf_path = Path("tests/fixtures/Caroling_Final.pdf")
    job = Job(
        id=job_id,
        original_filename="Caroling_Final.pdf",
        pdf_path=str(pdf_path),
        title="Caroling",
        status="pending"
    )
    db.add(job)
    db.commit()
    db.close()

    job_dir = tmp_path / "job_dns"
    job_dir.mkdir(parents=True, exist_ok=True)

    await PipelineOrchestrator.run_pipeline(
        job_id=job_id,
        job_dir=job_dir,
        pdf_path=pdf_path,
        session_factory=SessionFactory,
    )

    db = SessionFactory()
    completed_job = db.query(Job).filter(Job.id == job_id).first()
    assert completed_job.status == "completed", f"Job failed with: {completed_job.error_message}"
    assert completed_job.routed_cism is not None
    assert completed_job.decoder_result is not None
    db.close()


@pytest.mark.anyio
async def test_orchestrator_handles_missing_module_gracefully(tmp_path, monkeypatch):
    """Verify that when HTTP fails and fallback module is missing, an informative RuntimeError is stored."""
    from services.gateway_svc.database import Job
    from services.gateway_svc.main import SessionFactory
    from services.gateway_svc.orchestrator import PipelineOrchestrator
    import services.gateway_svc.orchestrator as orch_mod
    import builtins

    monkeypatch.setattr(orch_mod, "LAYOUT_SVC_URL", "http://unreachable-layout:8006")
    async def fast_post(*args, **kwargs):
        import httpx
        raise httpx.ConnectError("[Errno -3] Temporary failure in name resolution")
    monkeypatch.setattr(orch_mod, "_post_with_retry_and_fallback", fast_post)

    real_import = builtins.__import__
    def fake_import(name, *args, **kwargs):
        if "pdf_layout_svc" in name:
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    db = SessionFactory()
    job_id = "test_import_err_job"
    existing = db.query(Job).filter(Job.id == job_id).first()
    if existing:
        db.delete(existing)
        db.commit()

    job = Job(id=job_id, original_filename="dummy.pdf", pdf_path="dummy.pdf", title="Dummy", status="pending")
    db.add(job)
    db.commit()
    db.close()

    job_dir = tmp_path / "job_import_err"
    job_dir.mkdir(parents=True, exist_ok=True)

    await PipelineOrchestrator.run_pipeline(
        job_id=job_id,
        job_dir=job_dir,
        pdf_path=Path("dummy.pdf"),
        session_factory=SessionFactory,
    )

    db = SessionFactory()
    failed_job = db.query(Job).filter(Job.id == job_id).first()
    assert failed_job.status == "failed"
    assert "pdf-layout-svc (http://unreachable-layout:8006) is unreachable" in failed_job.error_message
    assert "parttrackr_net" in failed_job.error_message
    db.close()


def test_partitioned_musicxml_and_two_step_staff_decryption(tmp_path):
    """
    Verifies the two-step decryption:
    1. Piano staves detection: always 2 staves (RH treble + LH bass with brace).
    2. Remaining staves: treble = women, bass = men.
    3. Partitioned MusicXML output: score_piano.musicxml and score_vocals.musicxml
       are strictly synchronized by measure number.
    """
    from services.decoder_xml_svc.xml_compiler import XMLCompiler
    from services.decoder_xml_svc.midi_generator import MIDIGenerator
    from common.cism_schema import ScoreCISM, SystemData, MeasureData, StaffInfo, TrackData, NoteElement, BoundingBox

    st_vocal = StaffInfo(staff_id="s0_vocal", index=0, clef="treble", bracket_type="none", role="vocal_women", y_top=50, y_bot=90)
    st_p_rh = StaffInfo(staff_id="s0_p_rh", index=1, clef="treble", bracket_type="brace", role="piano_rh", y_top=130, y_bot=170)
    st_p_lh = StaffInfo(staff_id="s0_p_lh", index=2, clef="bass", bracket_type="brace", role="piano_lh", y_top=190, y_bot=230)

    m1 = MeasureData(
        measure_number=1,
        time_signature="4/4",
        tempo_bpm=120,
        quarter_length=4.0,
        raw_staves={
            "s0_vocal": TrackData(track_name="vocal", clef="treble", elements=[NoteElement(pitch="E5", duration_quarters=4.0)]),
            "s0_p_rh": TrackData(track_name="p_rh", clef="treble", elements=[NoteElement(pitch="G4", duration_quarters=4.0)]),
            "s0_p_lh": TrackData(track_name="p_lh", clef="bass", elements=[NoteElement(pitch="C3", duration_quarters=4.0)]),
        },
        tracks={
            "soprano_1": TrackData(track_name="soprano_1", clef="treble", elements=[NoteElement(pitch="E5", duration_quarters=4.0)]),
            "soprano_2": TrackData(track_name="soprano_2", clef="treble", elements=[NoteElement(pitch="E5", duration_quarters=4.0)]),
            "alto_1": TrackData(track_name="alto_1", clef="treble", elements=[NoteElement(pitch=None, duration_quarters=4.0, is_rest=True)]),
            "alto_2": TrackData(track_name="alto_2", clef="treble", elements=[NoteElement(pitch=None, duration_quarters=4.0, is_rest=True)]),
            "tenor_1": TrackData(track_name="tenor_1", clef="treble_8vb", elements=[NoteElement(pitch=None, duration_quarters=4.0, is_rest=True)]),
            "tenor_2": TrackData(track_name="tenor_2", clef="treble_8vb", elements=[NoteElement(pitch=None, duration_quarters=4.0, is_rest=True)]),
            "baritone_1": TrackData(track_name="baritone_1", clef="bass", elements=[NoteElement(pitch=None, duration_quarters=4.0, is_rest=True)]),
            "baritone_2": TrackData(track_name="baritone_2", clef="bass", elements=[NoteElement(pitch=None, duration_quarters=4.0, is_rest=True)]),
            "bass_1": TrackData(track_name="bass_1", clef="bass", elements=[NoteElement(pitch=None, duration_quarters=4.0, is_rest=True)]),
            "bass_2": TrackData(track_name="bass_2", clef="bass", elements=[NoteElement(pitch=None, duration_quarters=4.0, is_rest=True)]),
            "piano": TrackData(track_name="piano", clef="grand", elements=[NoteElement(pitch="G4", duration_quarters=4.0), NoteElement(pitch="C3", duration_quarters=4.0)]),
        }
    )

    sys0 = SystemData(
        system_index=0,
        page_num=1,
        measure_start=1,
        measure_end=1,
        bounding_box=BoundingBox(x=0, y=50, w=600, h=200),
        staves=[st_vocal, st_p_rh, st_p_lh],
        measures=[m1]
    )

    cism = ScoreCISM(
        score_id="test_partitioned",
        title="Partitioned Test Score",
        composer="Test Composer",
        total_systems=1,
        total_measures=1,
        has_piano=True,
        systems=[sys0]
    )

    out_dir = tmp_path / "partition_test"
    main_xml, piano_xml, vocals_xml, stems, summary = XMLCompiler.compile_score(cism, out_dir)

    assert main_xml.exists()
    assert piano_xml.exists()
    assert vocals_xml.exists()

    with open(piano_xml, "r", encoding="utf-8") as f:
        piano_content = f.read()
    assert "brace" in piano_content
    assert "Piano RH" in piano_content
    assert "Piano LH" in piano_content

    with open(vocals_xml, "r", encoding="utf-8") as f:
        vocals_content = f.read()
    assert "bracket" in vocals_content
    assert "Choir" in vocals_content

    main_midi, piano_midi, vocals_midi, stem_midis, sync_map = MIDIGenerator.compile_midi_and_sync_map(cism, out_dir)
    assert main_midi.exists()
    assert piano_midi.exists()
    assert vocals_midi.exists()





