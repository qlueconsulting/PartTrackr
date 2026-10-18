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
