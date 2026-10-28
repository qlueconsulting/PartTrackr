import tempfile
from pathlib import Path
import music21
import mido
import verovio
import pytest

from services.pdf_layout_svc.layout_engine import PDFLayoutEngine
from services.omr_ai_svc.hybrid_fusion_engine import HybridOMRFusionEngine
from services.voice_router_svc.router_engine import VoiceRouterEngine
from services.decoder_xml_svc.xml_compiler import XMLCompiler
from services.decoder_xml_svc.midi_generator import MIDIGenerator
from common.cism_schema import ScoreCISM


def test_piano_only_pipeline_extraction_and_brace_grouping(tmp_path):
    pdf_fixture = Path("tests/fixtures/scanned_choir_score.pdf")
    if not pdf_fixture.exists():
        pytest.skip("Scanned score fixture not found")

    hints = {
        "staves_per_system": 3,
        "time_signature": "6/8",
        "tempo_bpm": 96.0,
        "choral_voicing": "Tenor_Bass",
        "accompaniment_type": "piano",
        "piano_only": True,
        "total_measures": 112,
    }

    # Step 1: Layout processing (or reuse pre-extracted layout if available)
    layout_dir = tmp_path / "layout"
    layout_data = PDFLayoutEngine.process_pdf(pdf_fixture, layout_dir, dpi=150, score_hints=hints)
    assert layout_data["page_count"] == 8
    assert layout_data["total_systems"] >= 28

    # Step 2: CISM extraction with piano_only mode
    cism = HybridOMRFusionEngine.extract_cism(layout_data=layout_data, score_hints=hints)
    assert cism.metadata.get("piano_only") is True
    assert cism.has_piano is True
    assert cism.total_measures == 112

    # Step 3: Voice Routing
    routed_cism = VoiceRouterEngine.route_score(cism, score_hints=hints)

    # Step 4: MusicXML & MIDI Compilation
    out_compiled = tmp_path / "compiled"
    main_xml, piano_xml, vocals_xml, stem_xmls, summary = XMLCompiler.compile_score(routed_cism, out_compiled)
    main_midi, piano_midi, vocals_midi, stem_midis, sync_map = MIDIGenerator.compile_midi_and_sync_map(routed_cism, out_compiled)

    assert piano_xml.exists()
    assert piano_midi.exists()
    assert main_xml.exists()

    # Verify score_piano.musicxml contains grand staff with curly brace
    with open(piano_xml, "r", encoding="utf-8") as f:
        xml_text = f.read()

    assert '<group-symbol>brace</group-symbol>' in xml_text
    assert '<part-group number="1" type="start">' in xml_text

    # Parse and inspect with music21
    sc_piano = music21.converter.parse(str(piano_xml))
    assert len(sc_piano.parts) == 2
    assert sc_piano.parts[0].id == "piano_rh" or "RH" in sc_piano.parts[0].partName
    assert sc_piano.parts[1].id == "piano_lh" or "LH" in sc_piano.parts[1].partName

    rh_measures = list(sc_piano.parts[0].getElementsByClass(music21.stream.Measure))
    lh_measures = list(sc_piano.parts[1].getElementsByClass(music21.stream.Measure))
    assert len(rh_measures) == 112
    assert len(lh_measures) == 112

    # Verify active notes in Keyboard part
    rh_notes = list(sc_piano.parts[0].flatten().notes)
    lh_notes = list(sc_piano.parts[1].flatten().notes)
    assert len(rh_notes) > 50, f"Expected notes in piano RH, got {len(rh_notes)}"
    assert len(lh_notes) > 50, f"Expected notes in piano LH, got {len(lh_notes)}"

    # In piano_only mode, score.musicxml also contains strictly the Piano Grand Staff
    sc_main = music21.converter.parse(str(main_xml))
    assert len(sc_main.parts) == 2, f"Expected 2 parts in piano_only main score, got {len(sc_main.parts)}"

    # Verify Verovio SVG render succeeds
    tk = verovio.toolkit()
    assert tk.loadData(xml_text) is True
    assert tk.getPageCount() >= 1
    svg_page1 = tk.renderToSVG(1)
    assert len(svg_page1) > 1000

    # Verify MIDI contains Conductor and Piano Accompaniment
    mid = mido.MidiFile(str(piano_midi))
    assert len(mid.tracks) == 2
    assert mid.tracks[1].name == "Piano Accompaniment"
    piano_events = [m for m in mid.tracks[1] if m.type == "note_on" and m.velocity > 0]
    assert len(piano_events) > 100
