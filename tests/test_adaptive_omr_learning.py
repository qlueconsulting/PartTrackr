import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from common.learning_store import LearningManager, ScoreStyleFingerprint, StyleBlueprint
from services.pdf_layout_svc.layout_engine import PDFLayoutEngine
from services.omr_ai_svc.vision_llm_adapter import VisionLLMAdapter
from services.voice_router_svc.router_engine import VoiceRouterEngine
from services.gateway_svc.main import app

client = TestClient(app)


def test_learning_store_matching_and_teacher_signal(tmp_path):
    # 1. Match against foundational 3-staff male choir seed template
    fp = ScoreStyleFingerprint(
        staves_per_system=3,
        has_brace=True,
        has_bracket=False,
        time_signature="6/8",
        is_scanned=True
    )
    matched_bp, conf = LearningManager.match_style(fp, composer="Stewart")
    assert matched_bp is not None
    assert conf >= 0.70
    assert matched_bp.verified_config.get("staves_per_system") == 3

    # 2. In-context few-shot prompt generation
    prompt_txt = LearningManager.get_few_shot_prompt_text(fp, composer="Stewart")
    assert "LEARNED COMPOSER/EDITION STYLE TEMPLATE" in prompt_txt
    assert "Staff 0 (Top Staff): Vocal melody line" in prompt_txt
    assert "Staff 1 (Middle Staff): Piano Treble RH" in prompt_txt
    assert "Staff 2 (Bottom Staff): Piano Bass LH" in prompt_txt

    # 3. Record teacher signal from AI Helps
    hints = {
        "staves_per_system": 3,
        "time_signature": "6/8",
        "tempo_bpm": 108.0,
        "choral_voicing": "Tenor_Bass",
        "accompaniment_type": "piano",
        "total_measures": 56,
        "custom_instructions": "Bottom two staves are piano accompaniment; top staff is men's melody."
    }
    learned_bp = LearningManager.record_teacher_signal(
        job_id="test_job_1",
        title="Caroling Scanned Score",
        composer="K. Stewart",
        score_hints=hints
    )
    assert learned_bp is not None
    assert learned_bp.verified_config["time_signature"] == "6/8"
    assert learned_bp.verified_config["choral_voicing"] == "Tenor_Bass"


def test_scanned_score_morphological_debouncing_and_triplet_locking(tmp_path):
    pdf_fixture = Path("tests/fixtures/scanned_choir_score.pdf")
    if not pdf_fixture.exists():
        pytest.skip("Scanned choir score fixture not found")

    out_dir = tmp_path / "layout_scanned"
    # Process layout with deterministic 3-staff locking hint
    hints = {
        "staves_per_system": 3,
        "time_signature": "6/8",
        "choral_voicing": "Tenor_Bass",
        "accompaniment_type": "piano"
    }
    layout_data = PDFLayoutEngine.process_pdf(pdf_fixture, out_dir, dpi=150, score_hints=hints)

    assert layout_data["page_count"] >= 1
    p1 = layout_data["pages"][0]
    
    # Page 1 of media_1792361796541_e1c634ca.pdf has exactly 3 systems of 3 staves each (9 staves total)
    assert len(p1["systems"]) == 3, f"Expected 3 systems on page 1, got {len(p1['systems'])}"
    
    for sys_idx, s in enumerate(p1["systems"]):
        assert len(s["staves"]) == 3, f"System {sys_idx} should have exactly 3 staves, got {len(s['staves'])}"
        staves = s["staves"]
        # Staff 0: Vocal melody
        assert staves[0]["role"] in ("vocal_men", "vocal_lead", "vocal_soprano")
        assert staves[0]["bracket_type"] == "none"
        # Staff 1: Piano RH
        assert staves[1]["role"] == "piano_rh"
        assert staves[1]["bracket_type"] == "brace"
        # Staff 2: Piano LH
        assert staves[2]["role"] == "piano_lh"
        assert staves[2]["bracket_type"] == "brace"


def test_omr_abolishes_hallucinated_notes(tmp_path):
    # Verify _create_baseline_staves and CV fallback emits ONLY clean rests, zero fake pitches
    from common.cism_schema import StaffInfo
    staves = [
        StaffInfo(staff_id="p1_sys0_st0", index=0, clef="treble_8vb", bracket_type="none", role="vocal_men", y_top=100, y_bot=140, has_lyrics=True),
        StaffInfo(staff_id="p1_sys0_st1", index=1, clef="treble", bracket_type="brace", role="piano_rh", y_top=160, y_bot=200, has_lyrics=False),
        StaffInfo(staff_id="p1_sys0_st2", index=2, clef="bass", bracket_type="brace", role="piano_lh", y_top=220, y_bot=260, has_lyrics=False),
    ]

    # Baseline staves must NEVER contain hardcoded notes (like C3, G2, E4, C5)
    baseline = VisionLLMAdapter._create_baseline_staves(staves, quarter_length=3.0)
    for st_id, track in baseline.items():
        assert len(track.elements) == 1
        elem = track.elements[0]
        assert elem.is_rest is True, f"Track {st_id} element should be a rest"
        assert elem.pitch is None, f"Track {st_id} element should have pitch=None, got {elem.pitch}"
        assert elem.duration_quarters == 3.0, f"Duration should match measure quarter length 3.0"

    # CV fallback on nonexistent crop also emits clean rests
    cv_res = VisionLLMAdapter._recognize_from_crop_cv("nonexistent_path.png", staves, quarter_length=3.0)
    for st_id, track in cv_res.items():
        for elem in track.elements:
            assert elem.is_rest is True
            assert elem.pitch is None


def test_voice_router_male_zero_second_guessing():
    from common.cism_schema import ScoreCISM, SystemData, MeasureData, StaffInfo, TrackData, NoteElement, BoundingBox

    staves = [
        StaffInfo(staff_id="st0", index=0, clef="treble_8vb", bracket_type="none", role="vocal_men", y_top=10, y_bot=30, has_lyrics=True),
        StaffInfo(staff_id="st1", index=1, clef="treble", bracket_type="brace", role="piano_rh", y_top=40, y_bot=60, has_lyrics=False),
        StaffInfo(staff_id="st2", index=2, clef="bass", bracket_type="brace", role="piano_lh", y_top=70, y_bot=90, has_lyrics=False),
    ]

    # Measure with single vocal melody on st0
    raw_staves = {
        "st0": TrackData(
            track_name="st0",
            clef="treble_8vb",
            elements=[NoteElement(pitch="D4", duration_quarters=1.0, duration_type="quarter", offset_quarters=0.0, is_rest=False)]
        ),
        "st1": TrackData(
            track_name="st1",
            clef="treble",
            elements=[NoteElement(pitch=None, duration_quarters=1.0, duration_type="quarter", offset_quarters=0.0, is_rest=True)]
        ),
        "st2": TrackData(
            track_name="st2",
            clef="bass",
            elements=[NoteElement(pitch=None, duration_quarters=1.0, duration_type="quarter", offset_quarters=0.0, is_rest=True)]
        )
    }

    cism = ScoreCISM(
        score_id="male_test",
        title="Men's Song",
        composer="Stewart",
        page_count=1,
        total_systems=1,
        total_measures=1,
        has_piano=True,
        systems=[
            SystemData(
                system_index=0,
                page_num=1,
                bounding_box=BoundingBox(x=0, y=0, w=100, h=100),
                staves=staves,
                measures=[
                    MeasureData(
                        measure_number=1,
                        time_signature="6/8",
                        tempo_bpm=108.0,
                        quarter_length=3.0,
                        raw_staves=raw_staves
                    )
                ]
            )
        ]
    )

    # Route with score_hints specifying male choral voicing
    hints = {"choral_voicing": "Tenor_Bass"}
    routed = VoiceRouterEngine.route_score(cism, score_hints=hints)

    m1 = routed.systems[0].measures[0]
    # Male parts must have active note D4
    assert any(el.pitch == "D4" for el in m1.tracks["tenor_1"].elements)
    assert any(el.pitch == "D4" for el in m1.tracks["baritone_1"].elements)
    assert any(el.pitch == "D4" for el in m1.tracks["bass_1"].elements)

    # Soprano and Alto parts must be 100% rests (zero second guessing!)
    assert all(el.is_rest for el in m1.tracks["soprano_1"].elements)
    assert all(el.is_rest for el in m1.tracks["soprano_2"].elements)
    assert all(el.is_rest for el in m1.tracks["alto_1"].elements)
    assert all(el.is_rest for el in m1.tracks["alto_2"].elements)


def test_gateway_learning_blueprints_endpoint():
    resp = client.get("/api/v1/learning/blueprints")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert len(data) >= 1
    # Check that seed 3-staff male choir template is present
    assert any("3staff" in bp_id or "choral" in bp_id for bp_id in data.keys())
