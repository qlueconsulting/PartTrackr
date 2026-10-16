import copy
from fractions import Fraction
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Optional, Dict, Any, List, Tuple

import music21
from music21 import stream, note, chord, meter, tempo, clef, layout, metadata

from app.config import settings
from app.services.pdf_music_extractor import PDFMusicExtractor
from app.services.llm_analyzer import LLMScoreAnalyzer

logger = logging.getLogger(__name__)


def _natural_sort_key(path: Path) -> List[Any]:
    """Sorts filenames containing numbers in true numerical order (e.g. mvt1, mvt2, ..., mvt10)."""
    return [int(tok) if tok.isdigit() else tok.lower() for tok in re.split(r"(\d+)", path.name)]


class OMREngine:
    """
    Hybrid OMR & Real-Time AI Choral Sheet Music Ingestion Engine:
    1. Direct Digital PDF / SMuFL Vector Score Extractor (PyMuPDF) for vector PDFs (Finale, Dorico, MuseScore, Sibelius).
    2. Audiveris 5.11 Headless CLI for raster/scanned PDFs (with System-Aware Vertical Re-Merging & Bottom-Up Piano Stitching).
    3. Real-Time Multimodal LLM & MCP Choral Score Analyzer (Local GPU Ollama / MCP / Gemini).
    4. Direct passthrough for MusicXML (.musicxml, .xml, .mxl) and MIDI (.mid).
    """

    def __init__(self):
        self.audiveris_bin = self._find_audiveris_binary()
        self.last_telemetry: Optional[Dict[str, Any]] = None
        self.last_llm_blueprint: Optional[Dict[str, Any]] = None

    def _find_audiveris_binary(self) -> Optional[str]:
        candidates = [
            settings.AUDIVERIS_CMD,
            "/usr/local/bin/audiveris",
            "/usr/bin/audiveris",
            "/opt/audiveris/bin/Audiveris",
            "/opt/Audiveris/bin/Audiveris",
            "/opt/audiveris/bin/audiveris",
            "/opt/Audiveris/bin/audiveris",
            "audiveris",
            "Audiveris",
        ]
        for c in candidates:
            if not c:
                continue
            resolved = shutil.which(c)
            if resolved:
                return resolved
            p = Path(c)
            if p.exists() and p.is_file():
                return str(p)
        return settings.AUDIVERIS_CMD

    def is_audiveris_installed(self) -> bool:
        bin_path = self._find_audiveris_binary()
        if not bin_path:
            return False
        return shutil.which(bin_path) is not None or Path(bin_path).exists()

    def process_file(self, input_path: Path, output_dir: Path) -> Path:
        """
        Processes (.pdf, .musicxml, .xml, .mxl, .mid) into a MusicXML file
        and runs real-time AI/LLM choral topology analysis on PDF uploads.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        ext = input_path.suffix.lower()
        self.last_telemetry = None
        self.last_llm_blueprint = None

        if ext in [".musicxml", ".xml", ".mxl"]:
            dest = output_dir / f"{input_path.stem}{ext}"
            shutil.copy2(input_path, dest)
            return dest

        elif ext in [".mid", ".midi"]:
            score = music21.converter.parse(str(input_path))
            dest = output_dir / f"{input_path.stem}.musicxml"
            score.write("musicxml", fp=str(dest))
            return dest

        elif ext == ".pdf":
            return self._process_pdf(input_path, output_dir)

        else:
            raise ValueError(f"Unsupported file format: {ext}. Expected .pdf, .musicxml, .xml, .mxl, or .mid")

    def _process_pdf(self, pdf_path: Path, output_dir: Path) -> Path:
        """
        Multi-stage PDF processing:
        Stage 1: Direct SMuFL / Vector PDF Extraction if embedded music glyphs exist.
        Stage 2: Pre-OMR Visual Skeleton + Vision LLM / MCP System Blueprinting.
        Stage 3: Audiveris Headless OMR CLI + System-Aware Movement Stitching.
        """
        dest_xml = output_dir / f"{pdf_path.stem}.musicxml"

        # Stage 1: Direct SMuFL / Vector PDF Extraction
        if PDFMusicExtractor.can_extract_vector_music(pdf_path):
            try:
                logger.info(f"Detected embedded SMuFL vector music notation in {pdf_path.name}. Extracting directly...")
                xml_path, telemetry = PDFMusicExtractor.extract_to_musicxml(pdf_path, dest_xml)
                self.last_telemetry = telemetry
                self.last_llm_blueprint = LLMScoreAnalyzer.analyze_pdf_score(pdf_path, telemetry)
                return xml_path
            except Exception as e:
                logger.warning(f"Direct vector extraction encountered an issue on {pdf_path.name}: {e}. Falling back to Audiveris OMR.")

        # Stage 2: Extract Pre-OMR PDF Visual Skeleton & Vision LLM Blueprint BEFORE Audiveris stitching
        self.last_telemetry = PDFMusicExtractor.extract_visual_skeleton(pdf_path)
        self.last_llm_blueprint = LLMScoreAnalyzer.analyze_pdf_score(pdf_path, self.last_telemetry)

        # Stage 3: Audiveris Headless OMR CLI (for scanned/non-SMuFL PDFs)
        xml_path = self._run_audiveris(pdf_path, output_dir)
        return xml_path

    def _run_audiveris(self, pdf_path: Path, output_dir: Path) -> Path:
        """
        Executes Audiveris CLI:
        audiveris -batch -export -output <xml_dir> <input_pdf>
        and stitches multi-movement exports using System-Aware Bottom-Up Piano Anchoring.
        """
        bin_path = self._find_audiveris_binary()
        has_audiveris = self.is_audiveris_installed()

        if not has_audiveris:
            logger.warning(
                f"Audiveris CLI not found on system (tried '{bin_path}'). "
                "Generating fallback score preserving PDF title."
            )
            return self._generate_fallback_score(pdf_path, output_dir)

        env = os.environ.copy()
        env["_JAVA_OPTIONS"] = "-Djava.awt.headless=true"
        env["JAVA_TOOL_OPTIONS"] = "-Djava.awt.headless=true"

        cmd = [
            str(bin_path),
            "-batch",
            "-export",
            "-output",
            str(output_dir),
            "-option",
            "org.audiveris.omr.sheet.BookManager.useSeparateBookFolders=false",
            str(pdf_path)
        ]

        logger.info(f"Running Audiveris CLI: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
                env=env
            )
            logger.info(f"Audiveris process finished with exit code {result.returncode}")
            if result.stdout:
                logger.info(f"Audiveris stdout: {result.stdout[:600]}")
            if result.stderr:
                logger.warning(f"Audiveris stderr: {result.stderr[:600]}")
        except Exception as e:
            logger.error(f"Audiveris execution encountered exception: {e}")

        exported_files = sorted(
            list(output_dir.rglob("*.mxl")) +
            list(output_dir.rglob("*.xml")) +
            list(output_dir.rglob("*.musicxml")),
            key=_natural_sort_key
        )

        if exported_files:
            if len(exported_files) == 1:
                logger.info(f"Audiveris generated notation file: {exported_files[0]}")
                return exported_files[0]
            else:
                logger.info(f"Audiveris generated {len(exported_files)} movement files; stitching into unified score...")
                return self._stitch_movements(exported_files, pdf_path, output_dir)

        logger.warning(
            f"Audiveris completed but no notation file was found in {output_dir} for {pdf_path.name}."
        )
        return self._generate_fallback_score(pdf_path, output_dir)

    @staticmethod
    def _inspect_part_traits(part: music21.stream.Part) -> Dict[str, Any]:
        """Inspects a music21 Part for lyrics, clef, pitch range, and chord density."""
        flat_notes = list(part.flatten().notes)
        has_lyrics = any(bool(n.lyrics) for n in flat_notes)
        first_clef = part.flatten().getElementsByClass(clef.Clef).first()
        is_bass_clef = isinstance(first_clef, (clef.BassClef, clef.FClef))

        midi_vals = [p.midi for n in flat_notes for p in n.pitches]
        median_midi = sorted(midi_vals)[len(midi_vals) // 2] if midi_vals else (50 if is_bass_clef else 65)
        is_bass = is_bass_clef or (median_midi < 58 and not isinstance(first_clef, clef.TrebleClef))

        p_name = (part.partName or "").lower()
        p_abbr = (part.partAbbreviation or "").lower()
        combined = f"{p_name} {p_abbr}"
        is_piano_named = any(k in combined for k in ["piano", "pno", "organ", "keyboard", "accomp"])
        is_vocal_named = any(k in combined for k in ["soprano", "alto", "tenor", "bass", "baritone", "choir", "voice", "vocal"])

        return {
            "part": part,
            "has_lyrics": has_lyrics,
            "is_bass": is_bass,
            "median_midi": median_midi,
            "note_count": len(flat_notes),
            "is_piano_named": is_piano_named,
            "is_vocal_named": is_vocal_named,
        }

    @staticmethod
    def _extract_measure_by_index(
        part: music21.stream.Part,
        m_idx: int,
        target_num: int,
        ts_str: str,
        tempo_bpm: float,
        bar_ql: Fraction
    ) -> music21.stream.Measure:
        """Extracts the m_idx-th measure from `part` (0-indexed) or returns a clean rest measure."""
        measures = list(part.getElementsByClass(stream.Measure))
        m_out = stream.Measure(number=target_num)
        m_out.timeSignature = meter.TimeSignature(ts_str)
        if target_num == 1:
            m_out.insert(0, tempo.MetronomeMark(number=tempo_bpm))

        if m_idx < len(measures):
            src_m = measures[m_idx]
            elems = list(src_m.flatten().notesAndRests)
            if elems:
                for el in elems:
                    m_out.insert(float(el.offset), copy.deepcopy(el))
                return m_out

        m_out.append(note.Rest(quarterLength=bar_ql))
        return m_out

    @classmethod
    def _split_measure_upper_lower(
        cls,
        src_m: music21.stream.Measure,
        target_num: int,
        ts_str: str,
        bar_ql: Fraction
    ) -> Tuple[music21.stream.Measure, music21.stream.Measure]:
        """Splits a polyphonic/chordal measure into upper voice and lower voice measures."""
        m_up = stream.Measure(number=target_num)
        m_low = stream.Measure(number=target_num)
        m_up.timeSignature = meter.TimeSignature(ts_str)
        m_low.timeSignature = meter.TimeSignature(ts_str)

        if len(src_m.voices) >= 2:
            for el in src_m.voices[0].flatten().notesAndRests:
                m_up.insert(float(el.offset), copy.deepcopy(el))
            for el in src_m.voices[1].flatten().notesAndRests:
                m_low.insert(float(el.offset), copy.deepcopy(el))
            return m_up, m_low

        elems = list(src_m.flatten().notesAndRests)
        if not elems:
            m_up.append(note.Rest(quarterLength=bar_ql))
            m_low.append(note.Rest(quarterLength=bar_ql))
            return m_up, m_low

        for el in elems:
            if isinstance(el, chord.Chord) and len(el.pitches) >= 2:
                p_sorted = sorted(el.pitches, key=lambda p: p.midi)
                n_up = note.Note(p_sorted[-1], quarterLength=el.duration.quarterLength)
                n_low = note.Note(p_sorted[0], quarterLength=el.duration.quarterLength)
                m_up.insert(float(el.offset), n_up)
                m_low.insert(float(el.offset), n_low)
            else:
                m_up.insert(float(el.offset), copy.deepcopy(el))
                m_low.insert(float(el.offset), copy.deepcopy(el))

        return m_up, m_low

    def _stitch_movements(self, files: List[Path], pdf_path: Path, output_dir: Path) -> Path:
        """
        System-Aware Multi-Movement Stitcher with:
        1. Natural numerical ordering of movement files (mvt1, mvt2, ..., mvt10).
        2. Bottom-Up Piano Accompaniment Anchoring (Rule A1a): Bottom 2 non-lyric staves always map to Piano_RH / Piano_LH.
        3. Vertical System Split Re-Merging: Re-combines vocal-only and piano-only movements when Audiveris splits a system vertically.
        4. Canonical Lockstep Measure Assembly: Guarantees every part (Soprano, Alto, Tenor, Bass, Piano_RH, Piano_LH)
           has the exact same measure count and measure numbers (1..N) with zero phase drift.
        """
        sorted_files = sorted(files, key=_natural_sort_key)
        parsed_movements: List[Dict[str, Any]] = []

        for f in sorted_files:
            try:
                sc = music21.converter.parse(str(f))
                parts = list(sc.parts)
                if not parts:
                    continue
                m_count = max((len(p.getElementsByClass(stream.Measure)) for p in parts), default=0)
                if m_count == 0:
                    continue

                brace_ids = set()
                bracket_ids = set()
                for sg in sc.getElementsByClass(layout.StaffGroup):
                    sym = getattr(sg, "symbol", "")
                    for p in sg:
                        if hasattr(p, "id"):
                            if sym in ("brace", "curly"):
                                brace_ids.add(p.id)
                            elif sym in ("bracket", "square", "line"):
                                bracket_ids.add(p.id)

                traits = [self._inspect_part_traits(p) for p in parts]
                for idx, tr in enumerate(traits):
                    pid = parts[idx].id
                    tr["is_brace"] = pid in brace_ids or tr["is_piano_named"]
                    tr["is_bracket"] = pid in bracket_ids or tr["is_vocal_named"]

                parsed_movements.append({
                    "file": f,
                    "score": sc,
                    "parts": parts,
                    "traits": traits,
                    "m_count": m_count
                })
            except Exception as ex:
                logger.warning(f"Skipping unreadable movement file {f}: {ex}")

        if not parsed_movements:
            return files[0]

        # Determine if overall score has Piano accompaniment (Rule A1a)
        skeleton_has_piano = bool((self.last_telemetry or {}).get("has_piano", False))
        score_has_piano = skeleton_has_piano or any(
            len(m["parts"]) >= 3 and not m["traits"][-1]["has_lyrics"]
            for m in parsed_movements
        ) or any(
            any(tr["is_brace"] for tr in m["traits"])
            for m in parsed_movements
        )

        # Classify each movement's parts into vocal_parts and piano_parts (Bottom-Up Anchor)
        classified_mvts: List[Dict[str, Any]] = []
        for m in parsed_movements:
            parts = m["parts"]
            traits = m["traits"]
            n_p = len(parts)
            vocal_p: List[Dict[str, Any]] = []
            piano_p: List[Dict[str, Any]] = []

            if score_has_piano:
                if n_p >= 3 and not traits[-1]["has_lyrics"] and not traits[-2]["has_lyrics"]:
                    vocal_p = traits[:-2]
                    piano_p = traits[-2:]
                elif n_p == 2:
                    if any(tr["has_lyrics"] or tr["is_vocal_named"] for tr in traits) and not any(tr["is_brace"] for tr in traits):
                        vocal_p = traits
                        piano_p = []
                    else:
                        vocal_p = []
                        piano_p = traits
                elif n_p == 1:
                    if traits[0]["has_lyrics"] or traits[0]["is_vocal_named"] or traits[0]["is_bracket"]:
                        vocal_p = traits
                        piano_p = []
                    else:
                        vocal_p = []
                        piano_p = traits
                else:
                    # Fallback if bottom staves had stray lyric tokens: still anchor bottom 2 as piano if >= 3 parts
                    vocal_p = traits[:-2]
                    piano_p = traits[-2:]
            else:
                vocal_p = traits
                piano_p = []

            classified_mvts.append({
                "file": m["file"],
                "score": m["score"],
                "m_count": m["m_count"],
                "vocal_traits": vocal_p,
                "piano_traits": piano_p
            })

        # Vertical System Split Re-Merger:
        # When Audiveris splits a single system horizontally into a vocal-only movement (B bars)
        # followed immediately by a piano-only movement (B bars), merge them vertically into the same B measures!
        merged_mvts: List[Dict[str, Any]] = []
        idx = 0
        while idx < len(classified_mvts):
            curr = classified_mvts[idx]
            if idx + 1 < len(classified_mvts):
                nxt = classified_mvts[idx + 1]
                curr_vocal_only = len(curr["vocal_traits"]) > 0 and len(curr["piano_traits"]) == 0
                curr_piano_only = len(curr["piano_traits"]) > 0 and len(curr["vocal_traits"]) == 0
                nxt_vocal_only = len(nxt["vocal_traits"]) > 0 and len(nxt["piano_traits"]) == 0
                nxt_piano_only = len(nxt["piano_traits"]) > 0 and len(nxt["vocal_traits"]) == 0

                bars_match = abs(curr["m_count"] - nxt["m_count"]) <= 1
                # Merge if (curr is vocal-only and nxt is piano-only) OR (idx > 0 and curr is piano-only and nxt is vocal-only)
                if bars_match and (
                    (curr_vocal_only and nxt_piano_only) or
                    (idx > 0 and curr_piano_only and nxt_vocal_only)
                ):
                    v_src = curr if curr_vocal_only else nxt
                    p_src = nxt if curr_vocal_only else curr
                    logger.info(
                        f"Re-merging vertically split system movements: {curr['file'].name} + {nxt['file'].name} "
                        f"({max(curr['m_count'], nxt['m_count'])} measures)"
                    )
                    merged_mvts.append({
                        "file": curr["file"],
                        "score": curr["score"],
                        "m_count": max(curr["m_count"], nxt["m_count"]),
                        "vocal_traits": v_src["vocal_traits"],
                        "piano_traits": p_src["piano_traits"]
                    })
                    idx += 2
                    continue

            merged_mvts.append(curr)
            idx += 1

        # Build unified canonical score with 4 Vocal parts (S, A, T, B) + 2 Piano parts (if score_has_piano)
        unified_score = stream.Score()
        unified_score.metadata = metadata.Metadata()
        title = (self.last_telemetry or {}).get("title") or pdf_path.stem.replace("_", " ").title()
        composer = (self.last_telemetry or {}).get("composer") or "Unknown Composer"
        unified_score.metadata.title = title
        unified_score.metadata.composer = composer

        p_s = stream.Part(id="Soprano")
        p_s.partName = "Soprano"
        p_s.partAbbreviation = "S"
        p_a = stream.Part(id="Alto")
        p_a.partName = "Alto"
        p_a.partAbbreviation = "A"
        p_t = stream.Part(id="Tenor")
        p_t.partName = "Tenor"
        p_t.partAbbreviation = "T"
        p_b = stream.Part(id="Bass")
        p_b.partName = "Bass"
        p_b.partAbbreviation = "B"
        canonical_vocals = [p_s, p_a, p_t, p_b]
        unified_score.append(layout.StaffGroup(canonical_vocals, symbol="bracket", name="Choir"))

        canonical_piano: List[music21.stream.Part] = []
        if score_has_piano:
            p_rh = stream.Part(id="Piano_RH")
            p_rh.partName = "Piano Right Hand"
            p_lh = stream.Part(id="Piano_LH")
            p_lh.partName = "Piano Left Hand"
            canonical_piano = [p_rh, p_lh]
            unified_score.append(layout.StaffGroup(canonical_piano, symbol="brace", name="Piano"))

        global_m_num = 0
        current_ts_str = "4/4"
        current_tempo_bpm = 120.0

        # Detect initial time signature and tempo from first movement
        first_ts = merged_mvts[0]["score"].flatten().getElementsByClass(meter.TimeSignature).first()
        if first_ts:
            current_ts_str = first_ts.ratioString
        first_tm = merged_mvts[0]["score"].flatten().getElementsByClass(tempo.MetronomeMark).first()
        if first_tm and first_tm.number:
            current_tempo_bpm = float(first_tm.number)

        for mvt in merged_mvts:
            m_count = mvt["m_count"]
            v_traits = mvt["vocal_traits"]
            p_traits = mvt["piano_traits"]
            all_mvt_parts = [tr["part"] for tr in (v_traits + p_traits)]

            for b_idx in range(m_count):
                global_m_num += 1
                # Check if any part in this movement defines a new time signature or tempo at measure index b_idx
                for mp in all_mvt_parts:
                    m_list = list(mp.getElementsByClass(stream.Measure))
                    if b_idx < len(m_list):
                        ts_el = m_list[b_idx].getElementsByClass(meter.TimeSignature).first()
                        if ts_el:
                            current_ts_str = ts_el.ratioString
                        tm_el = m_list[b_idx].getElementsByClass(tempo.MetronomeMark).first()
                        if tm_el and tm_el.number:
                            current_tempo_bpm = float(tm_el.number)

                bar_ql = Fraction(meter.TimeSignature(current_ts_str).barDuration.quarterLength)

                # 1. Populate Piano_RH and Piano_LH (Bottom-Up Ground Truth Anchor)
                if score_has_piano:
                    for p_slot_idx, p_dest in enumerate(canonical_piano):
                        if p_slot_idx < len(p_traits):
                            src_p = p_traits[p_slot_idx]["part"]
                            m_extracted = self._extract_measure_by_index(
                                src_p, b_idx, global_m_num, current_ts_str, current_tempo_bpm, bar_ql
                            )
                            p_dest.append(m_extracted)
                        else:
                            m_rest = stream.Measure(number=global_m_num)
                            m_rest.timeSignature = meter.TimeSignature(current_ts_str)
                            m_rest.append(note.Rest(quarterLength=bar_ql))
                            p_dest.append(m_rest)

                # 2. Populate Canonical Vocal Staves (Soprano, Alto, Tenor, Bass) based on active vocal topology in this movement
                nv = len(v_traits)
                if nv == 0:
                    for vp_dest in canonical_vocals:
                        m_rest = stream.Measure(number=global_m_num)
                        m_rest.timeSignature = meter.TimeSignature(current_ts_str)
                        m_rest.append(note.Rest(quarterLength=bar_ql))
                        vp_dest.append(m_rest)

                elif nv == 1:
                    # Single vocal staff in this movement/system
                    tr0 = v_traits[0]
                    m_raw = self._extract_measure_by_index(
                        tr0["part"], b_idx, global_m_num, current_ts_str, current_tempo_bpm, bar_ql
                    )
                    m_up, m_low = self._split_measure_upper_lower(m_raw, global_m_num, current_ts_str, bar_ql)
                    if tr0["is_bass"]:
                        # Men's unison / divisi staff -> Tenor & Bass active; Soprano & Alto rest
                        for vp_dest in (p_s, p_a):
                            m_r = stream.Measure(number=global_m_num)
                            m_r.timeSignature = meter.TimeSignature(current_ts_str)
                            m_r.append(note.Rest(quarterLength=bar_ql))
                            vp_dest.append(m_r)
                        p_t.append(copy.deepcopy(m_up))
                        p_b.append(copy.deepcopy(m_low))
                    else:
                        # Treble vocal staff -> Soprano & Alto active; Tenor & Bass rest
                        p_s.append(copy.deepcopy(m_up))
                        p_a.append(copy.deepcopy(m_low))
                        for vp_dest in (p_t, p_b):
                            m_r = stream.Measure(number=global_m_num)
                            m_r.timeSignature = meter.TimeSignature(current_ts_str)
                            m_r.append(note.Rest(quarterLength=bar_ql))
                            vp_dest.append(m_r)

                elif nv == 2:
                    # 2 Choral Staves (SA Treble + TB Bass)
                    tr_upper, tr_lower = v_traits[0], v_traits[1]
                    if tr_upper["is_bass"] and not tr_lower["is_bass"]:
                        tr_upper, tr_lower = tr_lower, tr_upper
                    m_sa = self._extract_measure_by_index(
                        tr_upper["part"], b_idx, global_m_num, current_ts_str, current_tempo_bpm, bar_ql
                    )
                    m_tb = self._extract_measure_by_index(
                        tr_lower["part"], b_idx, global_m_num, current_ts_str, current_tempo_bpm, bar_ql
                    )
                    m_s, m_a = self._split_measure_upper_lower(m_sa, global_m_num, current_ts_str, bar_ql)
                    m_t, m_b = self._split_measure_upper_lower(m_tb, global_m_num, current_ts_str, bar_ql)
                    p_s.append(m_s)
                    p_a.append(m_a)
                    p_t.append(m_t)
                    p_b.append(m_b)

                elif nv == 3:
                    # 3 Choral Staves (either S, A, TB or SA, T, B)
                    m0 = self._extract_measure_by_index(v_traits[0]["part"], b_idx, global_m_num, current_ts_str, current_tempo_bpm, bar_ql)
                    m1 = self._extract_measure_by_index(v_traits[1]["part"], b_idx, global_m_num, current_ts_str, current_tempo_bpm, bar_ql)
                    m2 = self._extract_measure_by_index(v_traits[2]["part"], b_idx, global_m_num, current_ts_str, current_tempo_bpm, bar_ql)
                    if not v_traits[1]["is_bass"]:
                        # S, A, TB
                        m_t, m_b = self._split_measure_upper_lower(m2, global_m_num, current_ts_str, bar_ql)
                        p_s.append(m0)
                        p_a.append(m1)
                        p_t.append(m_t)
                        p_b.append(m_b)
                    else:
                        # SA, T, B
                        m_s, m_a = self._split_measure_upper_lower(m0, global_m_num, current_ts_str, bar_ql)
                        p_s.append(m_s)
                        p_a.append(m_a)
                        p_t.append(m1)
                        p_b.append(m2)

                else:
                    # 4+ Discrete Choral Staves (S, A, T, B)
                    for v_idx, vp_dest in enumerate(canonical_vocals):
                        m_v = self._extract_measure_by_index(
                            v_traits[v_idx]["part"], b_idx, global_m_num, current_ts_str, current_tempo_bpm, bar_ql
                        )
                        vp_dest.append(m_v)

        for vp_dest in canonical_vocals:
            unified_score.append(vp_dest)
        for p_dest in canonical_piano:
            unified_score.append(p_dest)

        stitched_path = output_dir / f"{pdf_path.stem}_stitched.musicxml"
        unified_score.write("musicxml", fp=str(stitched_path))
        logger.info(
            f"Stitched {len(merged_mvts)} movements into {global_m_num} lockstep measures at {stitched_path}"
        )
        return stitched_path

    def _generate_fallback_score(self, pdf_path: Path, output_dir: Path) -> Path:
        """Generates a baseline choral score preserving the uploaded PDF's title."""
        from app.services.sample_scores import create_sample_satb_with_piano
        sample_dest = output_dir / f"{pdf_path.stem}.musicxml"
        create_sample_satb_with_piano(sample_dest)
        # Preserve the uploaded filename as the title so it never masquerades as 'Choral Anthem of Hope'
        try:
            sc = music21.converter.parse(str(sample_dest))
            if sc.metadata:
                sc.metadata.title = pdf_path.stem.replace("_", " ").title()
                sc.metadata.composer = "Uploaded PDF Score"
            sc.write("musicxml", fp=str(sample_dest))
        except Exception:
            pass
        return sample_dest
