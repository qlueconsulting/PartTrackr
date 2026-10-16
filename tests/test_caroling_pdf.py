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


def test_multi_movement_stitching_and_vertical_remerge(tmp_path: Path):
    """
    Verifies that when Audiveris exports multiple movement files with:
    - Natural numerical filenames (mvt1, mvt2, mvt3, mvt4, mvt10)
    - Changing staff counts per system (2-staff Piano intro -> 3-staff Unison+Piano -> 6-staff SATB+Piano)
    - Vertically split systems (mvt3 = 5 bars Vocal only, mvt4 = 5 bars Piano only)
    OMREngine._stitch_movements + NotationProcessor:
    1. Sorts mvt10 AFTER mvt4 (not after mvt1).
    2. Re-merges vertically split mvt3 + mvt4 into simultaneous measures (total 16 measures, not 21).
    3. Anchors Piano to bottom 2 staves so Piano and Vocal parts never swap or separate.
    """
    from music21 import stream, note, meter, clef, layout
    from app.services.omr_service import OMREngine
    from app.services.notation_processor import NotationProcessor

    def make_part(pid: str, name: str, is_bass: bool, n_bars: int, pitch_str: str, lyric: str = "") -> stream.Part:
        p = stream.Part(id=pid)
        p.partName = name
        for b in range(1, n_bars + 1):
            m = stream.Measure(number=b)
            if b == 1:
                m.insert(0, clef.BassClef() if is_bass else clef.TrebleClef())
                m.timeSignature = meter.TimeSignature("3/4")
            n = note.Note(pitch_str, quarterLength=3.0)
            if lyric:
                n.lyric = f"{lyric}_{b}"
            m.append(n)
            p.append(m)
        return p

    # mvt1 (3 bars): 2-staff Piano Intro (no lyrics)
    s1 = stream.Score()
    s1.append(make_part("P1", "Piano RH", False, 3, "G4"))
    s1.append(make_part("P2", "Piano LH", True, 3, "C3"))
    f1 = tmp_path / "FirstNowell.mvt1.musicxml"
    s1.write("musicxml", fp=str(f1))

    # mvt2 (4 bars): 3-staff Men's Unison + Piano (1 Bass Vocal with lyrics + 2 Piano staves)
    s2 = stream.Score()
    s2.append(make_part("P1", "Men", True, 4, "E3", lyric="Nowell"))
    s2.append(make_part("P2", "Piano RH", False, 4, "G4"))
    s2.append(make_part("P3", "Piano LH", True, 4, "C3"))
    f2 = tmp_path / "FirstNowell.mvt2.musicxml"
    s2.write("musicxml", fp=str(f2))

    # mvt3 (5 bars): Vertically split system TOP HALF (1 Treble Vocal staff with lyrics, NO Piano)
    s3 = stream.Score()
    s3.append(make_part("P1", "Women", False, 5, "B4", lyric="Born"))
    f3 = tmp_path / "FirstNowell.mvt3.musicxml"
    s3.write("musicxml", fp=str(f3))

    # mvt4 (5 bars): Vertically split system BOTTOM HALF (2 Piano staves, NO Vocals)
    s4 = stream.Score()
    s4.append(make_part("P1", "Piano RH", False, 5, "D4"))
    s4.append(make_part("P2", "Piano LH", True, 5, "G2"))
    f4 = tmp_path / "FirstNowell.mvt4.musicxml"
    s4.write("musicxml", fp=str(f4))

    # mvt10 (4 bars): 6-staff Full SATB + Piano (tests natural sort order mvt10 > mvt4)
    s10 = stream.Score()
    s10.append(make_part("P1", "Soprano", False, 4, "C5", lyric="King"))
    s10.append(make_part("P2", "Alto", False, 4, "E4", lyric="King"))
    s10.append(make_part("P3", "Tenor", True, 4, "G3", lyric="King"))
    s10.append(make_part("P4", "Bass", True, 4, "C3", lyric="King"))
    s10.append(make_part("P5", "Piano RH", False, 4, "E4"))
    s10.append(make_part("P6", "Piano LH", True, 4, "C2"))
    f10 = tmp_path / "FirstNowell.mvt10.musicxml"
    s10.write("musicxml", fp=str(f10))

    engine = OMREngine()
    # Pass intentionally in alphabetical order (f1, f10, f2, f3, f4) to verify natural sort
    stitched_xml = engine._stitch_movements([f1, f10, f2, f3, f4], tmp_path / "FirstNowell.pdf", tmp_path)

    proc = NotationProcessor(stitched_xml)
    stems, analysis = proc.extract_all_stems()

    # Total measures must be 3 + 4 + 5 (re-merged from 5+5) + 4 = 16 measures
    assert len(analysis) == 16

    # mm. 1..3: Piano Intro only
    for m_num in (1, 2, 3):
        m_info = analysis[m_num - 1]
        assert m_info["active_parts"] == ["Piano"]

    # mm. 4..7: Men's Unison + Piano simultaneously
    for m_num in (4, 5, 6, 7):
        m_info = analysis[m_num - 1]
        assert "Piano" in m_info["active_parts"]
        for male in ("T1", "T2", "Bar1", "Bar2", "B1", "B2"):
            assert male in m_info["active_parts"]
        for female in ("S1", "S2", "A1", "A2"):
            assert female not in m_info["active_parts"]

    # mm. 8..12: Re-merged Women's Unison + Piano simultaneously (NOT separated into 5 vocal + 5 piano)
    for m_num in (8, 9, 10, 11, 12):
        m_info = analysis[m_num - 1]
        assert "Piano" in m_info["active_parts"]
        for female in ("S1", "S2", "A1", "A2"):
            assert female in m_info["active_parts"]

    # mm. 13..16 (mvt10): Full SATB + Piano simultaneously
    for m_num in (13, 14, 15, 16):
        m_info = analysis[m_num - 1]
        assert len(m_info["active_parts"]) == 11


def test_closed_loop_alternating_split_repair(tmp_path: Path):
    """
    Verifies that NotationProcessor._repair_alternating_vocal_piano_splits folds
    an alternating [N bars Vocal-only] + [N bars Piano-only] split inside a single score
    back into N simultaneous measures.
    """
    from music21 import stream, note, meter, layout
    from app.services.notation_processor import NotationProcessor

    sc = stream.Score()
    v_part = stream.Part(id="Vocal")
    v_part.partName = "Choir"
    p_part = stream.Part(id="Piano")
    p_part.partName = "Piano"

    # Bars 1..4: Vocal active, Piano resting
    # Bars 5..8: Vocal resting, Piano active
    for b in range(1, 9):
        mv = stream.Measure(number=b)
        mp = stream.Measure(number=b)
        if b == 1:
            mv.timeSignature = meter.TimeSignature("4/4")
            mp.timeSignature = meter.TimeSignature("4/4")
        if b <= 4:
            n = note.Note("C5", quarterLength=4.0)
            n.lyric = "La"
            mv.append(n)
            mp.append(note.Rest(quarterLength=4.0))
        else:
            mv.append(note.Rest(quarterLength=4.0))
            mp.append(note.Note("G3", quarterLength=4.0))
        v_part.append(mv)
        p_part.append(mp)

    sc.append(layout.StaffGroup([v_part], symbol="bracket", name="Choir"))
    sc.append(layout.StaffGroup([p_part], symbol="brace", name="Piano"))
    sc.append(v_part)
    sc.append(p_part)

    xml_path = tmp_path / "split_score.musicxml"
    sc.write("musicxml", fp=str(xml_path))

    proc = NotationProcessor(xml_path)
    stems, analysis = proc.extract_all_stems()

    # The 4 vocal-only + 4 piano-only bars must fold into 4 simultaneous bars
    assert len(analysis) == 4
    for m_info in analysis:
        assert "Piano" in m_info["active_parts"]
        assert len(m_info["active_parts"]) > 1

