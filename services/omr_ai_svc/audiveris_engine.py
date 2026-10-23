from __future__ import annotations
import copy
from fractions import Fraction
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Dict, Any, List, Optional, Tuple

import music21
from music21 import stream, note, chord, meter, tempo, clef, layout, metadata

from common.cism_schema import (
    ScoreCISM, SystemData, MeasureData, StaffInfo, TrackData, NoteElement, BoundingBox
)
from common.lockstep_utils import calculate_bar_quarter_length
from common.music_theory_engine import MusicTheoryEngine

logger = logging.getLogger("omr_ai_svc.audiveris")


def _natural_sort_key(path: Path) -> List[Any]:
    """Sorts filenames containing numbers in true numerical order (e.g. mvt1, mvt2, ..., mvt10)."""
    return [int(tok) if tok.isdigit() else tok.lower() for tok in re.split(r"(\d+)", path.name)]


class AudiverisEngine:
    """
    Production Audiveris 5.3+ Optical Music Recognition Engine:
    1. Executes Headless Audiveris CLI in batch export mode.
    2. Gathers multi-page / multi-movement exported MusicXML (.mxl, .xml, .musicxml).
    3. Stitches movements with System-Aware Bottom-Up Piano Accompaniment Anchoring.
    4. Automatically re-merges vertically split vocal and piano systems.
    5. Converts the unified music21 symbolic score into canonical ScoreCISM.
    """

    @classmethod
    def find_audiveris_binary(cls) -> Optional[str]:
        candidates = [
            os.environ.get("AUDIVERIS_CMD"),
            "/opt/audiveris/bin/Audiveris",
            "/opt/Audiveris/bin/Audiveris",
            "/opt/audiveris/bin/audiveris",
            "/opt/Audiveris/bin/audiveris",
            "/usr/local/bin/audiveris",
            "/usr/bin/audiveris",
            "audiveris",
            "Audiveris",
            r"C:\Program Files\Audiveris\bin\Audiveris.bat",
            r"C:\Program Files (x86)\Audiveris\bin\Audiveris.bat",
        ]
        for c in candidates:
            if not c:
                continue
            resolved = shutil.which(c)
            if resolved and os.path.isfile(resolved) and os.access(resolved, os.X_OK):
                return resolved
            p = Path(c)
            if p.exists() and p.is_file() and os.access(str(p), os.X_OK):
                return str(p)
        return None

    @classmethod
    def is_installed(cls) -> bool:
        bin_path = cls.find_audiveris_binary()
        if not bin_path:
            return False
        try:
            res = subprocess.run([bin_path, "-batch", "-help"], capture_output=True, timeout=15)
            return res.returncode == 0
        except Exception:
            return False

    @classmethod
    def process_pdf_to_cism(
        cls,
        pdf_path: Path,
        work_dir: Path,
        layout_data: Optional[Dict[str, Any]] = None,
        score_hints: Optional[Dict[str, Any]] = None,
        custom_instructions: Optional[str] = None
    ) -> ScoreCISM:
        """
        Runs Audiveris headless OMR, stitches movements, and converts to ScoreCISM.
        """
        work_dir.mkdir(parents=True, exist_ok=True)
        bin_path = cls.find_audiveris_binary()
        if not bin_path:
            raise FileNotFoundError("Audiveris binary not found on system.")

        env = os.environ.copy()
        env["_JAVA_OPTIONS"] = "-Djava.awt.headless=true"
        env["JAVA_TOOL_OPTIONS"] = "-Djava.awt.headless=true"

        cmd = [
            str(bin_path),
            "-batch",
            "-export",
            "-output",
            str(work_dir),
            "--",
            str(pdf_path)
        ]

        logger.info(f"Executing Audiveris CLI: {' '.join(cmd)}")
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
            logger.info(f"Audiveris stdout: {result.stdout[:500]}")
        if result.stderr:
            logger.warning(f"Audiveris stderr: {result.stderr[:500]}")

        exported_files = sorted(
            list(work_dir.rglob("*.mxl")) +
            list(work_dir.rglob("*.xml")) +
            list(work_dir.rglob("*.musicxml")),
            key=_natural_sort_key
        )

        if not exported_files:
            # Check if Audiveris saved directly in the PDF directory
            exported_files = sorted(
                list(pdf_path.parent.rglob("*.mxl")) +
                list(pdf_path.parent.rglob("*.xml")) +
                list(pdf_path.parent.rglob("*.musicxml")),
                key=_natural_sort_key
            )

        # Fallback retry: If PDF produced no files, retry using pre-rendered 300 DPI page images from layout_data
        if not exported_files and layout_data and layout_data.get("pages"):
            page_images = [
                Path(p["image_path"]) for p in layout_data["pages"]
                if p.get("image_path") and Path(p["image_path"]).exists()
            ]
            if page_images:
                logger.info(f"Retrying Audiveris OMR with {len(page_images)} pre-rendered 300 DPI page images...")
                img_cmd = [
                    str(bin_path),
                    "-batch",
                    "-export",
                    "-output",
                    str(work_dir),
                    "--"
                ] + [str(p) for p in page_images]
                img_res = subprocess.run(
                    img_cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=300,
                    env=env
                )
                logger.info(f"Audiveris image retry finished with exit code {img_res.returncode}")
                exported_files = sorted(
                    list(work_dir.rglob("*.mxl")) +
                    list(work_dir.rglob("*.xml")) +
                    list(work_dir.rglob("*.musicxml")),
                    key=_natural_sort_key
                )

        if not exported_files:
            err_msg = (
                f"Audiveris exited with code {result.returncode} but produced no MusicXML files in {work_dir}. "
                f"Stderr: {result.stderr.strip()[:400] if result.stderr else 'none'}. "
                f"Stdout: {result.stdout.strip()[:400] if result.stdout else 'none'}."
            )
            logger.warning(err_msg)
            raise RuntimeError(err_msg)

        stitched_score = cls._stitch_movements(exported_files, pdf_path, layout_data, score_hints)
        return cls._music21_score_to_cism(stitched_score, pdf_path, layout_data, score_hints)

    @classmethod
    def _inspect_part_traits(cls, part: music21.stream.Part) -> Dict[str, Any]:
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
            "first_clef_name": "bass" if is_bass_clef else "treble"
        }

    @classmethod
    def _stitch_movements(
        cls,
        files: List[Path],
        pdf_path: Path,
        layout_data: Optional[Dict[str, Any]],
        score_hints: Optional[Dict[str, Any]]
    ) -> music21.stream.Score:
        sorted_files = sorted(files, key=_natural_sort_key)
        parsed_mvts: List[Dict[str, Any]] = []

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

                traits = [cls._inspect_part_traits(p) for p in parts]
                for idx, tr in enumerate(traits):
                    pid = parts[idx].id
                    tr["is_brace"] = pid in brace_ids or tr["is_piano_named"]
                    tr["is_bracket"] = pid in bracket_ids or tr["is_vocal_named"]

                parsed_mvts.append({
                    "file": f,
                    "score": sc,
                    "parts": parts,
                    "traits": traits,
                    "m_count": m_count
                })
            except Exception as e:
                logger.warning(f"AudiverisEngine: could not parse movement file {f.name}: {e}")

        if not parsed_mvts:
            raise RuntimeError("No valid score movements could be parsed by music21.")

        if len(parsed_mvts) == 1:
            return parsed_mvts[0]["score"]

        # Check score has piano via hints, layout, or traits (Rule A1a)
        score_has_piano = bool(
            (score_hints or {}).get("accompaniment_type") == "piano"
            or (layout_data or {}).get("has_piano", False)
            or any(any(tr["is_brace"] for tr in m["traits"]) for m in parsed_mvts)
            or any(len(m["parts"]) >= 3 and not m["traits"][-1]["has_lyrics"] for m in parsed_mvts)
        )

        classified_mvts: List[Dict[str, Any]] = []
        for m in parsed_mvts:
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

        # Vertical System Split Re-Merger
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
                if bars_match and (
                    (curr_vocal_only and nxt_piano_only) or
                    (idx > 0 and curr_piano_only and nxt_vocal_only)
                ):
                    v_src = curr if curr_vocal_only else nxt
                    p_src = nxt if curr_vocal_only else curr
                    logger.info(
                        f"AudiverisEngine: Re-merging vertically split movements {curr['file'].name} + {nxt['file'].name}"
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

        # Stitch horizontally into unified score
        unified = stream.Score()
        unified.metadata = metadata.Metadata()
        unified.metadata.title = (score_hints or {}).get("title") or pdf_path.stem.replace("_", " ").title()
        unified.metadata.composer = (score_hints or {}).get("composer") or "Unknown Composer"

        max_vocal_parts = max((len(m["vocal_traits"]) for m in merged_mvts), default=1)
        vocal_out_parts: List[stream.Part] = []
        for vi in range(max_vocal_parts):
            p = stream.Part(id=f"Vocal_{vi + 1}")
            p.partName = f"Vocal {vi + 1}"
            vocal_out_parts.append(p)
            unified.append(p)

        piano_rh = stream.Part(id="Piano_RH")
        piano_rh.partName = "Piano Right Hand"
        piano_lh = stream.Part(id="Piano_LH")
        piano_lh.partName = "Piano Left Hand"
        if score_has_piano:
            unified.append(piano_rh)
            unified.append(piano_lh)

        global_measure_num = 1
        default_ts_str = (score_hints or {}).get("time_signature", "4/4")
        default_tempo_bpm = float((score_hints or {}).get("tempo_bpm", 120.0))
        bar_ql = Fraction(calculate_bar_quarter_length(default_ts_str))

        for m_block in merged_mvts:
            # Check if this movement has printed measure numbers that anchor its starting measure
            all_block_measures = [
                m.number for tr in (m_block["vocal_traits"] + m_block["piano_traits"])
                for m in tr["part"].getElementsByClass(stream.Measure)
                if m.number is not None and m.number > 0
            ]
            if all_block_measures:
                mvt_min = min(all_block_measures)
                mvt_max = max(all_block_measures)
                if mvt_min >= global_measure_num:
                    # Absolute printed numbering continues across movements
                    use_absolute = True
                    mvt_start_num = mvt_min
                    global_measure_num = mvt_min
                else:
                    # Movement restarts numbering from 1 (relative indexing 1..N)
                    use_absolute = False
                    mvt_start_num = mvt_min

                blk_len = max(m_block["m_count"], (mvt_max - mvt_min + 1))
            else:
                use_absolute = False
                mvt_start_num = 1
                blk_len = m_block["m_count"]

            for m_i in range(blk_len):
                cur_target_num = global_measure_num + m_i
                local_src_num = (mvt_start_num + m_i) if not use_absolute else cur_target_num

                # Stitch each vocal part with exact measure number alignment
                for vi, out_p in enumerate(vocal_out_parts):
                    if vi < len(m_block["vocal_traits"]):
                        src_part = m_block["vocal_traits"][vi]["part"]
                        m_obj = cls._extract_measure(
                            src_part, m_i, cur_target_num, default_ts_str, default_tempo_bpm, bar_ql,
                            src_measure_num=local_src_num
                        )
                    else:
                        m_obj = stream.Measure(number=cur_target_num)
                        m_obj.append(note.Rest(quarterLength=bar_ql))
                    out_p.append(m_obj)

                # Stitch piano staves with exact measure number alignment
                if score_has_piano:
                    p_traits = m_block["piano_traits"]
                    if len(p_traits) >= 2:
                        rh_m = cls._extract_measure(
                            p_traits[0]["part"], m_i, cur_target_num, default_ts_str, default_tempo_bpm, bar_ql,
                            src_measure_num=local_src_num
                        )
                        lh_m = cls._extract_measure(
                            p_traits[1]["part"], m_i, cur_target_num, default_ts_str, default_tempo_bpm, bar_ql,
                            src_measure_num=local_src_num
                        )
                    elif len(p_traits) == 1:
                        rh_m = cls._extract_measure(
                            p_traits[0]["part"], m_i, cur_target_num, default_ts_str, default_tempo_bpm, bar_ql,
                            src_measure_num=local_src_num
                        )
                        lh_m = stream.Measure(number=cur_target_num)
                        lh_m.append(note.Rest(quarterLength=bar_ql))
                    else:
                        rh_m = stream.Measure(number=cur_target_num)
                        rh_m.append(note.Rest(quarterLength=bar_ql))
                        lh_m = stream.Measure(number=cur_target_num)
                        lh_m.append(note.Rest(quarterLength=bar_ql))
                    piano_rh.append(rh_m)
                    piano_lh.append(lh_m)

            global_measure_num += blk_len

        return unified

    @classmethod
    def _extract_measure(
        cls,
        part: music21.stream.Part,
        m_idx: int,
        target_num: int,
        ts_str: str,
        tempo_bpm: float,
        bar_ql: Fraction,
        src_measure_num: Optional[int] = None
    ) -> music21.stream.Measure:
        m_out = stream.Measure(number=target_num)
        m_out.timeSignature = meter.TimeSignature(ts_str)
        if target_num == 1:
            m_out.insert(0, tempo.MetronomeMark(number=tempo_bpm))

        lookup_num = src_measure_num if src_measure_num is not None else target_num

        # 1. First attempt: match by exact measure number (prevents cross-part desynchronization!)
        src_m = None
        for m in part.getElementsByClass(stream.Measure):
            if m.number == lookup_num:
                src_m = m
                break

        # 2. Second attempt: match by index if measure numbers are absent
        if src_m is None:
            measures = list(part.getElementsByClass(stream.Measure))
            if m_idx < len(measures):
                cand = measures[m_idx]
                if cand.number is None or cand.number == 0:
                    src_m = cand

        if src_m is not None:
            elems = list(src_m.flatten().notesAndRests)
            if elems:
                for el in elems:
                    m_out.insert(float(el.offset), copy.deepcopy(el))
                # Preserve any rehearsal marks
                for rm in src_m.getElementsByClass(music21.expressions.RehearsalMark):
                    m_out.insert(0, copy.deepcopy(rm))
                return m_out

        m_out.append(note.Rest(quarterLength=bar_ql))
        return m_out

    @classmethod
    def _music21_score_to_cism(
        cls,
        score: music21.stream.Score,
        pdf_path: Path,
        layout_data: Optional[Dict[str, Any]],
        score_hints: Optional[Dict[str, Any]]
    ) -> ScoreCISM:
        title = (score_hints or {}).get("title") or getattr(score.metadata, "title", None) or pdf_path.stem.replace("_", " ").title()
        composer = (score_hints or {}).get("composer") or getattr(score.metadata, "composer", None) or "Unknown Composer"

        parts = list(score.parts)
        if not parts:
            raise ValueError("Parsed music21 score has no parts.")

        measures_by_part = [list(p.getElementsByClass(stream.Measure)) for p in parts]
        total_measures = max((len(m_list) for m_list in measures_by_part), default=0)

        # Step 1: Detect curved braces and piano naming from score layout, groups, and hints
        brace_part_ids = set()
        for sg in score.getElementsByClass(layout.StaffGroup):
            sym = getattr(sg, "symbol", "")
            if sym in ("brace", "curly"):
                for p in sg:
                    if hasattr(p, "id"):
                        brace_part_ids.add(p.id)

        traits = [cls._inspect_part_traits(p) for p in parts]
        for idx, tr in enumerate(traits):
            pid = parts[idx].id
            tr["is_brace"] = pid in brace_part_ids or tr["is_piano_named"]

        has_piano = bool(
            (score_hints or {}).get("accompaniment_type") == "piano"
            or (layout_data or {}).get("has_piano", False)
            or any(tr["is_brace"] for tr in traits)
            or any(tr["is_piano_named"] for tr in traits)
            or (len(parts) >= 3 and not traits[-1]["has_lyrics"] and not traits[-2]["has_lyrics"])
        )
        if (score_hints or {}).get("accompaniment_type") == "a_cappella":
            has_piano = False

        # Identify piano indices: piano is ALWAYS exactly two staves
        piano_indices = set()
        if has_piano:
            explicit_piano = [i for i, tr in enumerate(traits) if tr["is_brace"] or tr["is_piano_named"]]
            if len(explicit_piano) == 2:
                piano_indices = set(explicit_piano)
            elif len(parts) >= 3:
                # Bottom-up anchor: in choral scores with piano, bottom 2 staves are piano
                piano_indices = {len(parts) - 2, len(parts) - 1}
            elif len(parts) == 2 and not any(tr["has_lyrics"] for tr in traits):
                piano_indices = {0, 1}

        # Cross-reference with layout_data Pass 1 blueprint staves if available
        layout_staves = []
        if layout_data and layout_data.get("systems") and layout_data["systems"][0].get("staves"):
            layout_staves = layout_data["systems"][0]["staves"]

        staves_info: List[StaffInfo] = []
        piano_sorted_idx = sorted(list(piano_indices))
        for idx, p in enumerate(parts):
            tr = traits[idx]
            first_clef = p.flatten().getElementsByClass(clef.Clef).first()
            clef_str = "bass" if isinstance(first_clef, (clef.BassClef, clef.FClef)) else "treble"

            if idx in piano_indices:
                bracket = "brace"
                role = "piano_rh" if idx == piano_sorted_idx[0] else "piano_lh"
                clef_str = "treble" if role == "piano_rh" else "bass"
            else:
                bracket = "bracket"
                # Step 2: Unlabeled remaining staves: Treble = women parts, Bass = male parts
                p_name_lower = (p.partName or p.id or "").lower()
                if any(k in p_name_lower for k in ("men", "male", "tenor", "bass", "baritone", "t.", "b.")):
                    role = "vocal_men"
                elif any(k in p_name_lower for k in ("women", "soprano", "alto", "s.", "a.")):
                    role = "vocal_women"
                elif clef_str == "bass" or tr["is_bass"]:
                    role = "vocal_men"
                else:
                    role = "vocal_women"

            st_id = f"st_{idx}"
            # Synchronize with Pass 1 layout staves if counts match
            if len(parts) == len(layout_staves) and idx < len(layout_staves):
                lst = layout_staves[idx]
                if lst.get("role"):
                    role = lst["role"]
                if lst.get("clef"):
                    clef_str = lst["clef"]
                if lst.get("bracket_type"):
                    bracket = lst["bracket_type"]
                if lst.get("staff_id"):
                    st_id = lst["staff_id"]

            staves_info.append(
                StaffInfo(
                    staff_id=st_id,
                    index=idx,
                    clef=clef_str,
                    bracket_type=bracket,
                    role=role,
                    y_top=100.0 * idx,
                    y_bot=100.0 * idx + 50.0,
                    has_lyrics=(bracket != "brace" and tr["has_lyrics"]),
                    label=p.partName or ("Piano RH" if role == "piano_rh" else ("Piano LH" if role == "piano_lh" else ("Women" if role == "vocal_women" else "Men")))
                )
            )

        # Build measure maps for all parts indexed by exact measure number and metric offset
        # to ensure that when piecing parts back together, individual measure numbers align strictly.
        part_m_by_num: List[Dict[int, music21.stream.Measure]] = []
        part_m_by_offset: List[Dict[float, music21.stream.Measure]] = []
        part_rehearsal_marks: List[Dict[int, str]] = []

        for idx, p in enumerate(parts):
            num_map: Dict[int, music21.stream.Measure] = {}
            off_map: Dict[float, music21.stream.Measure] = {}
            rm_map: Dict[int, str] = {}
            for m in p.getElementsByClass(stream.Measure):
                if m.number is not None and m.number >= 0:
                    num_map[m.number] = m
                off_key = round(float(m.offset), 2)
                off_map[off_key] = m
                rms = list(m.getElementsByClass(music21.expressions.RehearsalMark))
                if rms and hasattr(rms[0], "content") and rms[0].content:
                    rm_map[m.number if m.number is not None else 0] = str(rms[0].content)

            part_m_by_num.append(num_map)
            part_m_by_offset.append(off_map)
            part_rehearsal_marks.append(rm_map)

        all_detected_numbers = set()
        for num_map in part_m_by_num:
            for num in num_map.keys():
                if num >= 0:
                    all_detected_numbers.add(num)

        start_num = min(all_detected_numbers) if all_detected_numbers else 1
        end_num = max(all_detected_numbers) if all_detected_numbers else total_measures
        if score_hints and score_hints.get("total_measures"):
            end_num = max(end_num, int(score_hints["total_measures"]))
        elif layout_data and layout_data.get("total_measures"):
            end_num = max(end_num, int(layout_data["total_measures"]))

        master_measure_numbers = list(range(start_num, end_num + 1))
        if not master_measure_numbers:
            master_measure_numbers = list(range(1, total_measures + 1))

        cism_measures: List[MeasureData] = []
        default_ts = (score_hints or {}).get("time_signature", "4/4")
        default_bpm = float((score_hints or {}).get("tempo_bpm", 120.0))

        for m_num in master_measure_numbers:
            raw_staves: Dict[str, TrackData] = {}
            m_ts = default_ts
            m_bpm = default_bpm
            m_ql = float(calculate_bar_quarter_length(m_ts))

            # Synchronize Rehearsal Marks across all parts
            reh_mark = None
            for rm_map in part_rehearsal_marks:
                if m_num in rm_map:
                    reh_mark = rm_map[m_num]
                    break

            for idx, p in enumerate(parts):
                st_id = staves_info[idx].staff_id
                num_map = part_m_by_num[idx]
                src_m = num_map.get(m_num)

                # Fallback to index only if part measures have no numbers or if index matches
                if src_m is None and not num_map and (m_num - 1) < len(measures_by_part[idx]):
                    cand = measures_by_part[idx][m_num - 1]
                    if cand.number is None or cand.number == 0 or cand.number == m_num:
                        src_m = cand

                elements: List[NoteElement] = []

                if src_m is not None:
                    if src_m.timeSignature:
                        m_ts = src_m.timeSignature.ratioString
                        m_ql = float(src_m.timeSignature.barDuration.quarterLength)

                    for el in src_m.flatten().notesAndRests:
                        q_dur = float(el.duration.quarterLength)
                        q_off = float(el.offset)
                        d_type = el.duration.type

                        if isinstance(el, note.Note):
                            p_name = el.pitch.nameWithOctave
                            m_pitch = el.pitch.midi
                            lyr = el.lyric
                            tie_str = el.tie.type if el.tie else None
                            acc_str = el.pitch.accidental.alter if el.pitch.accidental else None
                            acc = "#" if acc_str == 1 else ("b" if acc_str == -1 else None)
                            stem = getattr(el, "stemDirection", None)
                            if stem not in ("up", "down"):
                                stem = None

                            elements.append(
                                NoteElement(
                                    pitch=p_name,
                                    midi_pitch=m_pitch,
                                    duration_quarters=q_dur,
                                    duration_type=d_type,
                                    offset_quarters=q_off,
                                    stem_direction=stem,
                                    is_rest=False,
                                    is_chord=False,
                                    chord_pitches=[p_name],
                                    lyric=lyr,
                                    tie=tie_str,
                                    accidental=acc
                                )
                            )
                        elif isinstance(el, chord.Chord):
                            pitches = [p.nameWithOctave for p in el.pitches]
                            top_p = el.pitches[-1]
                            lyr = el.lyric
                            elements.append(
                                NoteElement(
                                    pitch=top_p.nameWithOctave,
                                    midi_pitch=top_p.midi,
                                    duration_quarters=q_dur,
                                    duration_type=d_type,
                                    offset_quarters=q_off,
                                    is_rest=False,
                                    is_chord=True,
                                    chord_pitches=pitches,
                                    lyric=lyr
                                )
                            )
                        elif isinstance(el, note.Rest):
                            elements.append(
                                NoteElement(
                                    pitch=None,
                                    duration_quarters=q_dur,
                                    duration_type=d_type,
                                    offset_quarters=q_off,
                                    is_rest=True
                                )
                            )

                if not elements:
                    elements = [
                        NoteElement(
                            pitch=None,
                            duration_quarters=m_ql,
                            duration_type="whole" if m_ql >= 4.0 else "half",
                            offset_quarters=0.0,
                            is_rest=True
                        )
                    ]

                raw_staves[st_id] = TrackData(
                    track_name=st_id,
                    clef=staves_info[idx].clef,
                    elements=elements
                )

            cism_measures.append(
                MeasureData(
                    measure_number=m_num,
                    time_signature=m_ts,
                    tempo_bpm=m_bpm,
                    quarter_length=m_ql,
                    rehearsal_mark=reh_mark,
                    raw_staves=raw_staves
                )
            )

        system_data = SystemData(
            system_index=0,
            page_num=1,
            bounding_box=BoundingBox(x=0, y=0, w=612, h=792),
            staves=staves_info,
            measures=cism_measures
        )

        return ScoreCISM(
            score_id=pdf_path.stem,
            title=title,
            composer=composer,
            page_count=1,
            total_systems=1,
            total_measures=total_measures,
            has_piano=has_piano,
            systems=[system_data],
            metadata={"omr_source": "audiveris_5.3", "original_pdf": pdf_path.name}
        )
