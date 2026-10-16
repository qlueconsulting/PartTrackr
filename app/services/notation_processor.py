from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import copy
import re

import music21
from music21 import stream, note, chord, meter, tempo, clef, layout, spanner

STEM_TAXONOMY = [
    "Piano",
    "S1",
    "S2",
    "A1",
    "A2",
    "T1",
    "T2",
    "Bar1",
    "Bar2",
    "B1",
    "B2"
]

STEM_METADATA = {
    "Piano": {"display": "Piano Accompaniment", "category": "accompaniment", "default_pan": 0.0, "gm_program": 0},
    "S1": {"display": "Soprano I", "category": "soprano", "default_pan": -0.6, "gm_program": 52},
    "S2": {"display": "Soprano II", "category": "soprano", "default_pan": -0.4, "gm_program": 52},
    "A1": {"display": "Alto I", "category": "alto", "default_pan": -0.2, "gm_program": 52},
    "A2": {"display": "Alto II", "category": "alto", "default_pan": 0.0, "gm_program": 52},
    "T1": {"display": "Tenor I", "category": "tenor", "default_pan": 0.2, "gm_program": 53},
    "T2": {"display": "Tenor II", "category": "tenor", "default_pan": 0.4, "gm_program": 53},
    "Bar1": {"display": "Baritone I", "category": "baritone", "default_pan": 0.5, "gm_program": 54},
    "Bar2": {"display": "Baritone II", "category": "baritone", "default_pan": 0.6, "gm_program": 54},
    "B1": {"display": "Bass I", "category": "bass", "default_pan": 0.7, "gm_program": 54},
    "B2": {"display": "Bass II", "category": "bass", "default_pan": 0.8, "gm_program": 54},
}

class MeasureTemplate:
    def __init__(self, number: int, quarter_length: Fraction, time_signature: str, tempo_bpm: float):
        self.number = number
        self.quarter_length = quarter_length
        self.time_signature = time_signature
        self.tempo_bpm = tempo_bpm
        self.start_seconds = 0.0
        self.duration_seconds = float(quarter_length) * (60.0 / tempo_bpm)

class NotationProcessor:
    """
    Processes musical scores into 11 standardized rehearsal stems adhering strictly to:
    Rule A: Bracket Cues & Dynamic Choral Voice Routing (Accompaniment-first timing grid,
            visual bracket cues, clefs, divisi separation, interlude suppression, authentic notes).
    Rule B: Metric Lockstep Synchronization & Duration Clamping (bar boundary clamping, 
            Fraction safety, exact measure duration matching, zero drift).
    """

    def __init__(self, score_path: Path, llm_blueprint: Optional[Dict[str, Any]] = None, user_hints: Optional[Any] = None):
        self.score_path = score_path
        self.llm_blueprint = llm_blueprint or {}
        if isinstance(user_hints, dict):
            self.user_hints = user_hints
        elif hasattr(user_hints, "model_dump"):
            self.user_hints = user_hints.model_dump()
        elif hasattr(user_hints, "dict"):
            self.user_hints = user_hints.dict()
        else:
            self.user_hints = {}

        self.raw_score: music21.stream.Score = music21.converter.parse(str(score_path))
        self.title = self._extract_title()
        self.composer = self._extract_composer()
        
        # Custom directives from user instructions
        self.custom_directives = self._parse_custom_instructions()
        self.custom_solos = self.custom_directives["solos"]
        self.custom_tacet = self.custom_directives["tacet"]
        self.custom_interludes = self.custom_directives["interludes"]

        # Identified parts
        self.accomp_parts: List[music21.stream.Part] = []
        self.vocal_parts: List[music21.stream.Part] = []
        self._classify_staves()
        self._repair_alternating_vocal_piano_splits()
        
        # Foundational measure structure (Rule A1a: Accompaniment first)
        self.measure_grid: List[MeasureTemplate] = []
        self._build_foundational_measure_grid()

    def _extract_title(self) -> str:
        if self.raw_score.metadata and self.raw_score.metadata.title:
            return self.raw_score.metadata.title
        # Check text expressions
        for el in self.raw_score.flatten().getElementsByClass(music21.expressions.TextExpression):
            if el.content and len(el.content) < 50:
                return el.content.strip()
        return self.score_path.stem.replace("_", " ").title()

    def _extract_composer(self) -> str:
        if self.raw_score.metadata and self.raw_score.metadata.composer:
            return self.raw_score.metadata.composer
        return "Unknown Composer"

    def _parse_custom_instructions(self) -> Dict[str, Any]:
        """
        Parses user score directives and measure instructions into structured constraints:
        - solos: Dict[int, str] (measure -> voice letter 'S', 'A', 'T', 'B')
        - tacet: Dict[str, Set[int]] (part group -> set of measure numbers)
        - interludes: Set[int] (instrumental prelude/interlude measures where vocal parts rest)
        """
        res = {
            "solos": {},
            "tacet": {
                "piano": set(), "vocal": set(), "men": set(), "women": set(),
                "soprano": set(), "alto": set(), "tenor": set(), "bass": set()
            },
            "interludes": set()
        }
        instr = str(self.user_hints.get("custom_instructions") or "").strip()
        if not instr:
            return res

        def _parse_measure_ranges(text: str) -> set:
            measures = set()
            for s, e in re.findall(r'(\d+)\s*(?:-|to)\s*(\d+)', text, re.I):
                s_i, e_i = int(s), int(e)
                measures.update(range(min(s_i, e_i), max(s_i, e_i) + 1))
            cleaned = re.sub(r'(\d+)\s*(?:-|to)\s*(\d+)', '', text)
            for s in re.findall(r'\b(\d+)\b', cleaned):
                measures.add(int(s))
            return measures

        normalized = re.sub(r'\bmm?\.\s*', 'm ', instr, flags=re.I)
        normalized = re.sub(r'\bbars?\.\s*', 'bar ', normalized, flags=re.I)
        clauses = re.split(r'[\n;]+|(?:\.\s+)|,', normalized)

        for clause in clauses:
            c = clause.strip().lower()
            if not c:
                continue
            ms = _parse_measure_ranges(c)
            if not ms:
                continue
            if any(w in c for w in ["prelude", "interlude", "intro", "instrumental"]):
                res["interludes"].update(ms)
            if "solo" in c:
                target = None
                if "sop" in c:
                    target = "S"
                elif "alt" in c:
                    target = "A"
                elif "ten" in c:
                    target = "T"
                elif "bass" in c or "bar" in c:
                    target = "B"
                if target:
                    for m in ms:
                        res["solos"][m] = target
            if any(w in c for w in ["tacet", "rest", "rests", "silent", "silence"]):
                if any(w in c for w in ["piano", "pno", "accomp", "keyboard"]):
                    res["tacet"]["piano"].update(ms)
                if any(w in c for w in ["men", "male"]):
                    res["tacet"]["men"].update(ms)
                if any(w in c for w in ["women", "female"]):
                    res["tacet"]["women"].update(ms)
                if any(w in c for w in ["soprano", "sopranos"]):
                    res["tacet"]["soprano"].update(ms)
                if any(w in c for w in ["alto", "altos"]):
                    res["tacet"]["alto"].update(ms)
                if any(w in c for w in ["tenor", "tenors"]):
                    res["tacet"]["tenor"].update(ms)
                if any(w in c for w in ["bass", "basses", "baritone"]):
                    res["tacet"]["bass"].update(ms)
                if any(w in c for w in ["vocal", "voices", "choir", "chorus", "all voices"]):
                    res["tacet"]["vocal"].update(ms)

        return res

    def _classify_staves(self):
        """
        Distinguishes piano accompaniment (Curvy Bracket / Brace `{`) from 
        vocal choral staves (Straight Bracket `[`).
        Rule A1: Straight Bracket groups vocal choral staves; Curvy Bracket groups piano accompaniment.
        """
        all_parts = list(self.raw_score.parts)
        if not all_parts:
            # Single stream wrapped in Score
            part = music21.stream.Part()
            for el in self.raw_score:
                part.append(el)
            all_parts = [part]

        accomp_hint = str(self.user_hints.get("accompaniment_type") or "").strip().lower()
        if accomp_hint == "a_cappella":
            # Explicit user hint: Pure a cappella score, no piano accompaniment
            self.accomp_parts = []
            self.vocal_parts = list(all_parts)
            return

        # Check for StaffGroups (braces vs brackets)
        brace_part_ids = set()
        bracket_part_ids = set()
        
        for sp in self.raw_score.getElementsByClass(layout.StaffGroup):
            if getattr(sp, "symbol", "") in ["brace", "curly"]:
                for p in sp:
                    if hasattr(p, "id"):
                        brace_part_ids.add(p.id)
            elif getattr(sp, "symbol", "") in ["bracket", "square", "line"]:
                for p in sp:
                    if hasattr(p, "id"):
                        bracket_part_ids.add(p.id)

        # Keyword heuristics for part names & instrument types
        accomp_keywords = ["piano", "pno", "organ", "keyboard", "acc.", "accomp", "clavecin", "harpsichord", "cembalo", "reduction"]
        vocal_keywords = ["soprano", "alto", "tenor", "bass", "baritone", "choir", "chorus", "voice", "vocal", "s.", "a.", "t.", "b."]

        for part in all_parts:
            p_name = (part.partName or "").lower()
            p_abbr = (part.partAbbreviation or "").lower()
            p_id = str(part.id).lower()
            combined_name = f"{p_name} {p_abbr} {p_id}"

            # Check if this part has lyrics (strong indicator of vocal part)
            has_lyrics = any(bool(n.lyrics) for n in part.flatten().notes)

            is_brace = part.id in brace_part_ids
            is_bracket = part.id in bracket_part_ids

            if is_brace or any(k in combined_name for k in accomp_keywords):
                self.accomp_parts.append(part)
            elif is_bracket or has_lyrics:
                self.vocal_parts.append(part)
            elif any(k in combined_name for k in vocal_keywords):
                self.vocal_parts.append(part)
            else:
                self.vocal_parts.append(part)

        # Apply accompaniment_type hints or bottom-up heuristics
        if accomp_hint in ["piano", "reduction"] and not self.accomp_parts:
            if len(all_parts) >= 3:
                self.accomp_parts = list(all_parts[-2:])
                self.vocal_parts = [p for p in all_parts if p not in self.accomp_parts]
            elif len(all_parts) == 2:
                self.vocal_parts = [all_parts[0]]
                self.accomp_parts = [all_parts[1]]
        elif not self.accomp_parts and len(all_parts) >= 3:
            candidate_bottom = all_parts[-2:]
            if not any(any(bool(n.lyrics) for n in p.flatten().notes) for p in candidate_bottom):
                self.accomp_parts = list(candidate_bottom)
                self.vocal_parts = [p for p in all_parts if p not in self.accomp_parts]

    def _repair_alternating_vocal_piano_splits(self):
        """
        Closed-loop self-correction pass:
        Detects if any system was split vertically into [N bars Vocal-only] followed immediately
        by [N bars Piano-only] (with N >= 2) and folds the Piano measures back into the Vocal measures
        so Vocal and Piano play simultaneously and measure counts are not inflated.
        """
        if not self.accomp_parts or not self.vocal_parts:
            return

        all_parts = self.vocal_parts + self.accomp_parts
        max_len = max((len(p.getElementsByClass(stream.Measure)) for p in all_parts), default=0)
        if max_len < 4:
            return

        # Ensure sequential 1..max_len measure indexing across all parts
        part_measures: Dict[int, List[music21.stream.Measure]] = {}
        for idx, p in enumerate(all_parts):
            ms = list(p.getElementsByClass(stream.Measure))
            for m_i, m in enumerate(ms):
                m.number = m_i + 1
            part_measures[idx] = ms

        n_vocal = len(self.vocal_parts)
        # Classify each measure index 0..max_len-1 as 'V' (vocal only), 'P' (piano only), 'VP' (both), or 'R' (rest)
        bar_states = []
        for m_i in range(max_len):
            v_cnt = sum(
                len(part_measures[p_i][m_i].flatten().notes)
                for p_i in range(n_vocal)
                if m_i < len(part_measures[p_i])
            )
            p_cnt = sum(
                len(part_measures[p_i][m_i].flatten().notes)
                for p_i in range(n_vocal, len(all_parts))
                if m_i < len(part_measures[p_i])
            )
            if v_cnt > 0 and p_cnt == 0:
                bar_states.append("V")
            elif p_cnt > 0 and v_cnt == 0:
                bar_states.append("P")
            elif v_cnt > 0 and p_cnt > 0:
                bar_states.append("VP")
            else:
                bar_states.append("R")

        # Group into contiguous state runs
        runs = []
        for m_i, st in enumerate(bar_states):
            if not runs or runs[-1]["state"] != st:
                runs.append({"state": st, "start": m_i, "end": m_i})
            else:
                runs[-1]["end"] = m_i

        # Identify (V_run followed by P_run of matching length >= 2)
        indices_to_delete = set()
        r_idx = 0
        while r_idx + 1 < len(runs):
            r1 = runs[r_idx]
            r2 = runs[r_idx + 1]
            len1 = r1["end"] - r1["start"] + 1
            len2 = r2["end"] - r2["start"] + 1
            if r1["state"] == "V" and r2["state"] == "P" and len1 >= 2 and len1 == len2:
                # Copy piano measures from r2 into r1
                for offset in range(len1):
                    src_idx = r2["start"] + offset
                    dst_idx = r1["start"] + offset
                    for p_i in range(n_vocal, len(all_parts)):
                        if src_idx < len(part_measures[p_i]) and dst_idx < len(part_measures[p_i]):
                            src_m = part_measures[p_i][src_idx]
                            dst_m = part_measures[p_i][dst_idx]
                            for el in list(dst_m.flatten().notesAndRests):
                                dst_m.remove(el, recurse=True)
                            for el in src_m.flatten().notesAndRests:
                                dst_m.insert(float(el.offset), copy.deepcopy(el))
                    indices_to_delete.add(src_idx)
                r_idx += 2
            else:
                r_idx += 1

        if not indices_to_delete:
            return

        # Rebuild parts without the redundant split measures and renumber 1..N
        for p_i, p in enumerate(all_parts):
            ms = part_measures[p_i]
            kept = [m for i, m in enumerate(ms) if i not in indices_to_delete]
            for old_m in list(p.getElementsByClass(stream.Measure)):
                p.remove(old_m)
            for new_num, m in enumerate(kept, start=1):
                m.number = new_num
                p.append(m)

    def _build_foundational_measure_grid(self):
        """
        Rule A1a: Always start with the accompaniment (if available) to give a basis 
        for measure counts, and then apply the other parts onto the foundational measure structure.
        """
        all_parts = list(self.raw_score.parts)
        source_parts = self.accomp_parts if self.accomp_parts else self.vocal_parts
        if not source_parts:
            source_parts = all_parts

        # Gather maximum contiguous measure sequence across all parts so no part is truncated
        measure_numbers = []
        for p in (source_parts + all_parts):
            m_nums = [m.number for m in p.getElementsByClass(stream.Measure)]
            if len(m_nums) > len(measure_numbers):
                measure_numbers = m_nums

        if not measure_numbers:
            measure_numbers = [1]

        # Determine time signatures and tempos
        current_ts = meter.TimeSignature("4/4")
        current_tempo = 120.0

        hint_ts = self.user_hints.get("time_signature")
        if hint_ts:
            try:
                current_ts = meter.TimeSignature(str(hint_ts).strip())
            except Exception:
                pass

        hint_bpm = self.user_hints.get("tempo_bpm")
        if hint_bpm:
            try:
                current_tempo = float(hint_bpm)
            except Exception:
                pass

        # Scan for initial time signature or tempo in score if not explicitly set by hints
        first_ts = self.raw_score.flatten().getElementsByClass(meter.TimeSignature).first()
        if first_ts and not hint_ts:
            current_ts = first_ts
        first_tempo = self.raw_score.flatten().getElementsByClass(tempo.MetronomeMark).first()
        if first_tempo and first_tempo.number and not hint_bpm:
            current_tempo = float(first_tempo.number)

        cumulative_seconds = 0.0

        for m_num in measure_numbers:
            # Check if any part defines a new TS or tempo at this measure (if not overridden by hint)
            for p in (source_parts + all_parts):
                m = p.measure(m_num)
                if m is not None:
                    if not hint_ts:
                        ts = m.getElementsByClass(meter.TimeSignature).first()
                        if ts:
                            current_ts = ts
                    if not hint_bpm:
                        tm = m.getElementsByClass(tempo.MetronomeMark).first()
                        if tm and tm.number:
                            current_tempo = float(tm.number)
                    if (ts if not hint_ts else None) or (tm if not hint_bpm else None):
                        break

            bar_ql = Fraction(current_ts.barDuration.quarterLength)
            template = MeasureTemplate(
                number=m_num,
                quarter_length=bar_ql,
                time_signature=current_ts.ratioString,
                tempo_bpm=current_tempo
            )
            template.start_seconds = cumulative_seconds
            cumulative_seconds += template.duration_seconds
            self.measure_grid.append(template)

        # Enforce user hint for total_measures (Rule B: Exact measure count guarantee)
        hint_total_m = self.user_hints.get("total_measures")
        if hint_total_m and isinstance(hint_total_m, int) and hint_total_m > 0:
            if len(self.measure_grid) > hint_total_m:
                self.measure_grid = self.measure_grid[:hint_total_m]
            elif len(self.measure_grid) < hint_total_m:
                last_tpl = self.measure_grid[-1] if self.measure_grid else MeasureTemplate(1, Fraction(4, 1), "4/4", 120.0)
                cumulative_seconds = self.measure_grid[-1].start_seconds + self.measure_grid[-1].duration_seconds if self.measure_grid else 0.0
                start_num = len(self.measure_grid) + 1
                for m_idx in range(start_num, hint_total_m + 1):
                    pad_tpl = MeasureTemplate(
                        number=m_idx,
                        quarter_length=last_tpl.quarter_length,
                        time_signature=last_tpl.time_signature,
                        tempo_bpm=last_tpl.tempo_bpm
                    )
                    pad_tpl.start_seconds = cumulative_seconds
                    cumulative_seconds += pad_tpl.duration_seconds
                    self.measure_grid.append(pad_tpl)

    def extract_all_stems(self) -> Tuple[Dict[str, music21.stream.Score], List[Dict[str, Any]]]:
        """
        Main orchestration method:
        1. Extract Piano Accompaniment (Rule A5: absolute ground truth, zero hallucination).
        2. Route Choral Voices dynamically based on brackets, clefs, divisi, solos.
        3. Clamp and pad every measure to lockstep bar duration (Rule B).
        4. Build measure analysis JSON.
        """
        stem_streams: Dict[str, music21.stream.Score] = {}

        # 1. Extract Accompaniment (Curvy Bracket)
        piano_score = self._extract_piano_accompaniment()
        stem_streams["Piano"] = piano_score

        # 2. Extract 10 Vocal Parts
        vocal_scores = self._route_vocal_parts()
        for key in ["S1", "S2", "A1", "A2", "T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
            stem_streams[key] = vocal_scores.get(key, self._create_empty_stem(key))

        # 3. Rule B: Metric Lockstep Clamping on EVERY stem
        for key in STEM_TAXONOMY:
            stem_streams[key] = self._enforce_metric_lockstep(key, stem_streams[key])

        # 4. Generate Measure Analysis & Interlude Audit
        analysis_data = self._generate_measure_analysis(stem_streams)

        return stem_streams, analysis_data

    def _extract_piano_accompaniment(self) -> music21.stream.Score:
        """
        Extracts the Piano Accompaniment strictly adhering to Rule A5:
        - DO NOT invent, fabricate, or hallucinate notes or chords for the piano that are not written in the score.
        - Accompaniment must match the composer's printed notes exactly.
        """
        pno_score = stream.Score()
        pno_part = stream.Part()
        pno_part.partName = "Piano Accompaniment"
        pno_part.id = "Piano"

        if not self.accomp_parts:
            # Pure a cappella score: create empty measures matching the grid
            for t in self.measure_grid:
                m = stream.Measure(number=t.number)
                m.timeSignature = meter.TimeSignature(t.time_signature)
                rest = note.Rest(quarterLength=t.quarter_length)
                m.append(rest)
                pno_part.append(m)
            pno_score.append(pno_part)
            return pno_score

        # Combine accompaniment parts if grand staff (treble + bass)
        for t in self.measure_grid:
            m_out = stream.Measure(number=t.number)
            m_out.timeSignature = meter.TimeSignature(t.time_signature)
            m_out.append(tempo.MetronomeMark(number=t.tempo_bpm))

            # Check if piano is explicitly tacet in this measure per user directive
            if t.number in getattr(self, "custom_tacet", {}).get("piano", set()):
                m_out.append(note.Rest(quarterLength=t.quarter_length))
                pno_part.append(m_out)
                continue

            notes_in_measure = []
            for p in self.accomp_parts:
                src_m = p.measure(t.number)
                if src_m is not None:
                    # Collect all notes and chords verbatim without alteration
                    for el in src_m.flatten().notesAndRests:
                        # Copy element to preserve printed pitch, accidental, duration, velocity
                        notes_in_measure.append((el.offset, copy.deepcopy(el)))

            if not notes_in_measure:
                m_out.append(note.Rest(quarterLength=t.quarter_length))
            else:
                # Insert notes at exact original offsets
                for offset, el in sorted(notes_in_measure, key=lambda x: x[0]):
                    m_out.insert(offset, el)

            pno_part.append(m_out)

        pno_score.append(pno_part)
        return pno_score

    def _route_vocal_parts(self) -> Dict[str, music21.stream.Score]:
        """
        Dynamic Choral Voice Routing (Rule A):
        Handles:
        - Single Bass Clef (Men's unison -> T1, T2, Bar1, Bar2, B1, B2)
        - Single Treble Clef (Women's unison -> S1, S2, A1, A2)
        - 1 Staff with Divisi Chords / Polyphony
        - 2 Choral Staves (SA + TB)
        - 4 Discrete Choral Staves (Full SATB)
        - Solos & Instrumental Interludes
        """
        results: Dict[str, music21.stream.Score] = {k: stream.Score() for k in STEM_TAXONOMY if k != "Piano"}
        for k, sc in results.items():
            p = stream.Part()
            p.partName = STEM_METADATA[k]["display"]
            p.id = k
            sc.append(p)

        n_vocal = len(self.vocal_parts)

        # Check if score has instrumental prelude/interlude where vocal staves are absent or resting
        interlude_measures = set()
        for t in self.measure_grid:
            m_num = t.number
            has_vocal_notes = False
            for vp in self.vocal_parts:
                vm = vp.measure(m_num)
                if vm and len(vm.flatten().notes) > 0:
                    has_vocal_notes = True
                    break
            if not has_vocal_notes:
                interlude_measures.add(m_num)

        # Incorporate user-specified custom interlude measures from directives
        if getattr(self, "custom_interludes", None):
            interlude_measures.update(self.custom_interludes)

        if n_vocal == 0:
            # No vocal staves (pure instrumental score), all vocal parts rest
            for k in results:
                for t in self.measure_grid:
                    m = self._create_rest_measure(t)
                    results[k].parts[0].append(m)
            return self._finalize_vocal_routing(results)

        # Explicit choral voicing hints
        voicing = str(self.user_hints.get("choral_voicing") or "auto").strip().upper()
        if voicing == "TTBB":
            self._route_ttbb_voices(results, interlude_measures)
            return self._finalize_vocal_routing(results)
        elif voicing == "SSAA":
            self._route_ssaa_voices(results, interlude_measures)
            return self._finalize_vocal_routing(results)
        elif voicing == "UNISON":
            self._route_unison_voices(results, interlude_measures)
            return self._finalize_vocal_routing(results)
        elif voicing == "SA_TB" and n_vocal == 2:
            self._route_sa_staff(self.vocal_parts[0], results, interlude_measures)
            self._route_tb_staff(self.vocal_parts[1], results, interlude_measures)
            return self._finalize_vocal_routing(results)
        elif voicing == "SAB" and n_vocal == 3:
            self._route_discrete_staff(self.vocal_parts[0], ["S1", "S2"], results, interlude_measures)
            self._route_discrete_staff(self.vocal_parts[1], ["A1", "A2"], results, interlude_measures)
            self._route_discrete_staff(self.vocal_parts[2], ["Bar1", "Bar2", "B1", "B2", "T1", "T2"], results, interlude_measures)
            return self._finalize_vocal_routing(results)

        elif n_vocal == 1:
            # Single vocal staff: inspect clef, labels, divisi
            single_part = self.vocal_parts[0]
            self._route_single_vocal_staff(single_part, results, interlude_measures)

        elif n_vocal == 2:
            # 2 Choral Staves (SA Treble + TB Bass)
            p1, p2 = self.vocal_parts[0], self.vocal_parts[1]
            # Check clef order: ensure p1 is female (treble) and p2 is male (bass)
            if self._is_bass_part(p1) and not self._is_bass_part(p2):
                p1, p2 = p2, p1
            self._route_sa_staff(p1, results, interlude_measures)
            self._route_tb_staff(p2, results, interlude_measures)

        elif n_vocal == 4:
            # 4 Discrete Staves (SATB)
            # Map staves by name or order (Soprano, Alto, Tenor, Bass)
            s_part, a_part, t_part, b_part = self._order_satb_parts(self.vocal_parts)
            self._route_discrete_staff(s_part, ["S1", "S2"], results, interlude_measures)
            self._route_discrete_staff(a_part, ["A1", "A2"], results, interlude_measures)
            self._route_discrete_staff(t_part, ["T1", "T2"], results, interlude_measures)
            self._route_discrete_staff(b_part, ["Bar1", "Bar2", "B1", "B2"], results, interlude_measures)

        else:
            # Flexible mapping for 3, 5, or more staves
            self._route_arbitrary_vocal_staves(self.vocal_parts, results, interlude_measures)

        return self._finalize_vocal_routing(results)

    def _finalize_vocal_routing(self, results: Dict[str, music21.stream.Score]) -> Dict[str, music21.stream.Score]:
        """
        Applies post-routing filters including custom tacet directives and custom solos across vocal parts.
        """
        results = self._apply_custom_solos(results)
        return self._apply_custom_tacet(results)

    def _apply_custom_solos(self, results: Dict[str, music21.stream.Score]) -> Dict[str, music21.stream.Score]:
        if not hasattr(self, "custom_solos") or not self.custom_solos:
            return results

        grid_by_num = {t.number: t for t in self.measure_grid}

        for m_num, solo_target in self.custom_solos.items():
            t = grid_by_num.get(m_num)
            if not t:
                continue

            for stem_name, score in results.items():
                if not score.parts:
                    continue
                # If this stem is NOT the solo target, silence it in measure m_num
                if not stem_name.startswith(solo_target):
                    part = score.parts[0]
                    m = part.measure(m_num)
                    if m is not None:
                        part.replace(m, self._create_rest_measure(t))

        return results

    def _apply_custom_tacet(self, results: Dict[str, music21.stream.Score]) -> Dict[str, music21.stream.Score]:
        if not hasattr(self, "custom_tacet") or not self.custom_tacet:
            return results

        men_stems = {"T1", "T2", "Bar1", "Bar2", "B1", "B2"}
        women_stems = {"S1", "S2", "A1", "A2"}
        sop_stems = {"S1", "S2"}
        alto_stems = {"A1", "A2"}
        tenor_stems = {"T1", "T2"}
        bass_stems = {"Bar1", "Bar2", "B1", "B2"}

        grid_by_num = {t.number: t for t in self.measure_grid}

        for stem_name, score in results.items():
            if not score.parts:
                continue
            part = score.parts[0]

            # Determine measures that should be silenced for this stem
            silence_measures = set()
            if "vocal" in self.custom_tacet:
                silence_measures.update(self.custom_tacet["vocal"])
            if stem_name in men_stems and "men" in self.custom_tacet:
                silence_measures.update(self.custom_tacet["men"])
            if stem_name in women_stems and "women" in self.custom_tacet:
                silence_measures.update(self.custom_tacet["women"])
            if stem_name in sop_stems and "soprano" in self.custom_tacet:
                silence_measures.update(self.custom_tacet["soprano"])
            if stem_name in alto_stems and "alto" in self.custom_tacet:
                silence_measures.update(self.custom_tacet["alto"])
            if stem_name in tenor_stems and "tenor" in self.custom_tacet:
                silence_measures.update(self.custom_tacet["tenor"])
            if stem_name in bass_stems and "bass" in self.custom_tacet:
                silence_measures.update(self.custom_tacet["bass"])

            if not silence_measures:
                continue

            # Replace silenced measures with rest measures matching the grid
            for m_num in silence_measures:
                m = part.measure(m_num)
                if m is not None:
                    t = grid_by_num.get(m_num)
                    if t:
                        part.replace(m, self._create_rest_measure(t))

        return results

    def _is_bass_part(self, part: music21.stream.Part) -> bool:
        first_clef = part.flatten().getElementsByClass(clef.Clef).first()
        if isinstance(first_clef, (clef.BassClef, clef.FClef)):
            return True
        name = (part.partName or "").lower()
        return any(k in name for k in ["bass", "tenor", "men", "baritone", "t/b", "tb"])

    def _order_satb_parts(self, parts: List[music21.stream.Part]) -> Tuple[music21.stream.Part, music21.stream.Part, music21.stream.Part, music21.stream.Part]:
        assigned = {"S": None, "A": None, "T": None, "B": None}
        unassigned = []

        for p in parts:
            name = (p.partName or "").lower()
            abbr = (p.partAbbreviation or "").lower()
            tag = f"{name} {abbr}"
            if "soprano" in tag or re.search(r"\bs\b", tag):
                assigned["S"] = p
            elif "alto" in tag or re.search(r"\ba\b", tag):
                assigned["A"] = p
            elif "tenor" in tag or re.search(r"\bt\b", tag):
                assigned["T"] = p
            elif "bass" in tag or re.search(r"\bb\b", tag):
                assigned["B"] = p
            else:
                unassigned.append(p)

        # Fallback to order in score if not all resolved
        order_keys = ["S", "A", "T", "B"]
        for k in order_keys:
            if assigned[k] is None and unassigned:
                assigned[k] = unassigned.pop(0)

        # Ensure none are None
        for i, k in enumerate(order_keys):
            if assigned[k] is None:
                assigned[k] = parts[min(i, len(parts) - 1)]

        return assigned["S"], assigned["A"], assigned["T"], assigned["B"]

    def _route_single_vocal_staff(self, staff: music21.stream.Part, results: Dict[str, music21.stream.Score], interludes: set):
        """
        Single staff under straight bracket:
        - Bass Clef / Men's unison -> T1, T2, Bar1, Bar2, B1, B2 (female rest)
        - Treble Clef / Women's unison -> S1, S2, A1, A2 (male rest)
        - Solo markings -> route to solo section only
        - Divisi -> upper stems to voice 1, lower to voice 2
        """
        first_clef = staff.flatten().getElementsByClass(clef.Clef).first()
        is_bass = isinstance(first_clef, (clef.BassClef, clef.FClef))
        p_name = (staff.partName or "").lower()

        is_men = is_bass or "men" in p_name or "tenor" in p_name or "bass" in p_name
        is_women = not is_bass or "women" in p_name or "soprano" in p_name or "alto" in p_name

        for t in self.measure_grid:
            m_num = t.number
            src_m = staff.measure(m_num)

            # Instrumental interlude check
            if m_num in interludes or src_m is None or len(src_m.flatten().notes) == 0:
                for k in results:
                    results[k].parts[0].append(self._create_rest_measure(t))
                continue

            # Check for Solo text expression
            is_solo, solo_target = self._check_solo(src_m, m_num)

            # Check for divisi / chords
            has_chords = any(isinstance(n, chord.Chord) for n in src_m.flatten().notes)

            if is_solo and solo_target:
                # Solo voice active, all others rest
                for k in results:
                    if k.startswith(solo_target):
                        results[k].parts[0].append(self._clone_measure(src_m, t))
                    else:
                        results[k].parts[0].append(self._create_rest_measure(t))
            elif is_men and not is_women:
                # Men's staff
                if has_chords:
                    m_upper, m_lower = self._separate_divisi(src_m, t)
                    for k in ["T1", "T2"]:
                        results[k].parts[0].append(copy.deepcopy(m_upper))
                    for k in ["Bar1", "Bar2", "B1", "B2"]:
                        results[k].parts[0].append(copy.deepcopy(m_lower))
                else:
                    m_cloned = self._clone_measure(src_m, t)
                    for k in ["T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
                        results[k].parts[0].append(copy.deepcopy(m_cloned))
                for k in ["S1", "S2", "A1", "A2"]:
                    results[k].parts[0].append(self._create_rest_measure(t))
            elif is_women and not is_men:
                # Women's staff
                if has_chords:
                    m_upper, m_lower = self._separate_divisi(src_m, t)
                    results["S1"].parts[0].append(copy.deepcopy(m_upper))
                    results["S2"].parts[0].append(copy.deepcopy(m_lower))
                    results["A1"].parts[0].append(copy.deepcopy(m_upper))
                    results["A2"].parts[0].append(copy.deepcopy(m_lower))
                else:
                    m_cloned = self._clone_measure(src_m, t)
                    for k in ["S1", "S2", "A1", "A2"]:
                        results[k].parts[0].append(copy.deepcopy(m_cloned))
                for k in ["T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
                    results[k].parts[0].append(self._create_rest_measure(t))
            else:
                # General unison / SA+TB single staff: if chords, separate upper/lower
                if has_chords:
                    m_upper, m_lower = self._separate_divisi(src_m, t)
                    for k in ["S1", "S2", "T1", "T2"]:
                        results[k].parts[0].append(copy.deepcopy(m_upper))
                    for k in ["A1", "A2", "Bar1", "Bar2", "B1", "B2"]:
                        results[k].parts[0].append(copy.deepcopy(m_lower))
                else:
                    m_cloned = self._clone_measure(src_m, t)
                    for k in results:
                        results[k].parts[0].append(copy.deepcopy(m_cloned))

    def _route_sa_staff(self, sa_staff: music21.stream.Part, results: Dict[str, music21.stream.Score], interludes: set):
        """Routes SA female staff to S1, S2, A1, A2."""
        for t in self.measure_grid:
            m_num = t.number
            src_m = sa_staff.measure(m_num)
            if m_num in interludes or src_m is None or len(src_m.flatten().notes) == 0:
                for k in ["S1", "S2", "A1", "A2"]:
                    results[k].parts[0].append(self._create_rest_measure(t))
                continue

            # Divisi / polyphony separation
            has_chords = any(isinstance(n, chord.Chord) for n in src_m.flatten().notes)
            has_voices = len(src_m.voices) > 1

            if has_voices:
                # Voice 1 -> S1/S2, Voice 2 -> A1/A2
                v1_m = self._measure_from_voice(src_m.voices[0], t)
                v2_m = self._measure_from_voice(src_m.voices[1], t)
                results["S1"].parts[0].append(copy.deepcopy(v1_m))
                results["S2"].parts[0].append(copy.deepcopy(v1_m))
                results["A1"].parts[0].append(copy.deepcopy(v2_m))
                results["A2"].parts[0].append(copy.deepcopy(v2_m))
            elif has_chords:
                m_upper, m_lower = self._separate_divisi(src_m, t)
                results["S1"].parts[0].append(copy.deepcopy(m_upper))
                results["S2"].parts[0].append(copy.deepcopy(m_upper))
                results["A1"].parts[0].append(copy.deepcopy(m_lower))
                results["A2"].parts[0].append(copy.deepcopy(m_lower))
            else:
                m_cloned = self._clone_measure(src_m, t)
                results["S1"].parts[0].append(copy.deepcopy(m_cloned))
                results["S2"].parts[0].append(copy.deepcopy(m_cloned))
                results["A1"].parts[0].append(copy.deepcopy(m_cloned))
                results["A2"].parts[0].append(copy.deepcopy(m_cloned))

    def _route_tb_staff(self, tb_staff: music21.stream.Part, results: Dict[str, music21.stream.Score], interludes: set):
        """Routes TB male staff to T1, T2, Bar1, Bar2, B1, B2."""
        for t in self.measure_grid:
            m_num = t.number
            src_m = tb_staff.measure(m_num)
            if m_num in interludes or src_m is None or len(src_m.flatten().notes) == 0:
                for k in ["T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
                    results[k].parts[0].append(self._create_rest_measure(t))
                continue

            has_chords = any(isinstance(n, chord.Chord) for n in src_m.flatten().notes)
            has_voices = len(src_m.voices) > 1

            if has_voices:
                v1_m = self._measure_from_voice(src_m.voices[0], t)
                v2_m = self._measure_from_voice(src_m.voices[1], t)
                results["T1"].parts[0].append(copy.deepcopy(v1_m))
                results["T2"].parts[0].append(copy.deepcopy(v1_m))
                results["Bar1"].parts[0].append(copy.deepcopy(v2_m))
                results["Bar2"].parts[0].append(copy.deepcopy(v2_m))
                results["B1"].parts[0].append(copy.deepcopy(v2_m))
                results["B2"].parts[0].append(copy.deepcopy(v2_m))
            elif has_chords:
                m_upper, m_lower = self._separate_divisi(src_m, t)
                results["T1"].parts[0].append(copy.deepcopy(m_upper))
                results["T2"].parts[0].append(copy.deepcopy(m_upper))
                results["Bar1"].parts[0].append(copy.deepcopy(m_lower))
                results["Bar2"].parts[0].append(copy.deepcopy(m_lower))
                results["B1"].parts[0].append(copy.deepcopy(m_lower))
                results["B2"].parts[0].append(copy.deepcopy(m_lower))
            else:
                m_cloned = self._clone_measure(src_m, t)
                for k in ["T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
                    results[k].parts[0].append(copy.deepcopy(m_cloned))

    def _route_discrete_staff(self, staff: music21.stream.Part, targets: List[str], results: Dict[str, music21.stream.Score], interludes: set):
        """Routes a single discrete section staff (e.g. Soprano) to its sub-parts (e.g. S1, S2)."""
        for t in self.measure_grid:
            m_num = t.number
            src_m = staff.measure(m_num)
            if m_num in interludes or src_m is None or len(src_m.flatten().notes) == 0:
                for k in targets:
                    results[k].parts[0].append(self._create_rest_measure(t))
                continue

            has_chords = any(isinstance(n, chord.Chord) for n in src_m.flatten().notes)
            if has_chords and len(targets) >= 2:
                m_upper, m_lower = self._separate_divisi(src_m, t)
                # Split targets into upper half and lower half
                mid = len(targets) // 2
                for k in targets[:mid]:
                    results[k].parts[0].append(copy.deepcopy(m_upper))
                for k in targets[mid:]:
                    results[k].parts[0].append(copy.deepcopy(m_lower))
            else:
                m_cloned = self._clone_measure(src_m, t)
                for k in targets:
                    results[k].parts[0].append(copy.deepcopy(m_cloned))

    def _route_arbitrary_vocal_staves(self, parts: List[music21.stream.Part], results: Dict[str, music21.stream.Score], interludes: set):
        """Heuristic mapping for 3-part (SAB / SSA / TBB) and 5+-part choral staff layouts."""
        if len(parts) == 3 and not any(
            any(k in (p.partName or "").lower() for k in ["sop", "alt", "ten", "bar", "bass"])
            for p in parts
        ):
            # 3 unnamed vocal staves: check if middle staff is treble (S, A, Men) or bass (SA, T, B)
            if not self._is_bass_part(parts[1]):
                self._route_discrete_staff(parts[0], ["S1", "S2"], results, interludes)
                self._route_discrete_staff(parts[1], ["A1", "A2"], results, interludes)
                self._route_discrete_staff(parts[2], ["T1", "T2", "Bar1", "Bar2", "B1", "B2"], results, interludes)
            else:
                self._route_discrete_staff(parts[0], ["S1", "S2", "A1", "A2"], results, interludes)
                self._route_discrete_staff(parts[1], ["T1", "T2"], results, interludes)
                self._route_discrete_staff(parts[2], ["Bar1", "Bar2", "B1", "B2"], results, interludes)
        else:
            default_groups = [
                ["S1", "S2"],
                ["A1", "A2"],
                ["T1", "T2"],
                ["Bar1", "Bar2", "B1", "B2"]
            ]
            for i, p in enumerate(parts):
                p_name = (p.partName or "").lower()
                if "sop" in p_name:
                    self._route_discrete_staff(p, ["S1", "S2"], results, interludes)
                elif "alt" in p_name:
                    self._route_discrete_staff(p, ["A1", "A2"], results, interludes)
                elif "ten" in p_name:
                    self._route_discrete_staff(p, ["T1", "T2"], results, interludes)
                elif "bar" in p_name:
                    self._route_discrete_staff(p, ["Bar1", "Bar2"], results, interludes)
                elif "bass" in p_name:
                    self._route_discrete_staff(p, ["B1", "B2"], results, interludes)
                else:
                    targets = default_groups[min(i, len(default_groups) - 1)]
                    self._route_discrete_staff(p, targets, results, interludes)

        # Fill any unassigned stems with rests
        for k in results:
            while len(results[k].parts[0].getElementsByClass(stream.Measure)) < len(self.measure_grid):
                idx = len(results[k].parts[0].getElementsByClass(stream.Measure))
                results[k].parts[0].append(self._create_rest_measure(self.measure_grid[idx]))

    def _route_ttbb_voices(self, results: Dict[str, music21.stream.Score], interludes: set):
        """Routes vocal staves strictly to Men's voices (T1, T2, Bar1, Bar2, B1, B2). Female stems rest."""
        for k in ["S1", "S2", "A1", "A2"]:
            for t in self.measure_grid:
                results[k].parts[0].append(self._create_rest_measure(t))

        men_keys = ["T1", "T2", "Bar1", "Bar2", "B1", "B2"]
        n_v = len(self.vocal_parts)
        if n_v == 1:
            staff = self.vocal_parts[0]
            for t in self.measure_grid:
                m_num = t.number
                src_m = staff.measure(m_num)
                if m_num in interludes or src_m is None or len(src_m.flatten().notes) == 0:
                    for k in men_keys:
                        results[k].parts[0].append(self._create_rest_measure(t))
                    continue
                has_chords = any(isinstance(n, chord.Chord) for n in src_m.flatten().notes)
                if has_chords:
                    m_up, m_low = self._separate_divisi(src_m, t)
                    for k in ["T1", "T2"]:
                        results[k].parts[0].append(copy.deepcopy(m_up))
                    for k in ["Bar1", "Bar2", "B1", "B2"]:
                        results[k].parts[0].append(copy.deepcopy(m_low))
                else:
                    m_cloned = self._clone_measure(src_m, t)
                    for k in men_keys:
                        results[k].parts[0].append(copy.deepcopy(m_cloned))
        elif n_v == 2:
            self._route_discrete_staff(self.vocal_parts[0], ["T1", "T2"], results, interludes)
            self._route_discrete_staff(self.vocal_parts[1], ["Bar1", "Bar2", "B1", "B2"], results, interludes)
        elif n_v == 3:
            self._route_discrete_staff(self.vocal_parts[0], ["T1"], results, interludes)
            self._route_discrete_staff(self.vocal_parts[1], ["T2"], results, interludes)
            self._route_discrete_staff(self.vocal_parts[2], ["Bar1", "Bar2", "B1", "B2"], results, interludes)
        else:
            self._route_discrete_staff(self.vocal_parts[0], ["T1"], results, interludes)
            self._route_discrete_staff(self.vocal_parts[1], ["T2"], results, interludes)
            self._route_discrete_staff(self.vocal_parts[2], ["Bar1", "Bar2"], results, interludes)
            self._route_discrete_staff(self.vocal_parts[3], ["B1", "B2"], results, interludes)

    def _route_ssaa_voices(self, results: Dict[str, music21.stream.Score], interludes: set):
        """Routes vocal staves strictly to Women's voices (S1, S2, A1, A2). Male stems rest."""
        for k in ["T1", "T2", "Bar1", "Bar2", "B1", "B2"]:
            for t in self.measure_grid:
                results[k].parts[0].append(self._create_rest_measure(t))

        women_keys = ["S1", "S2", "A1", "A2"]
        n_v = len(self.vocal_parts)
        if n_v == 1:
            staff = self.vocal_parts[0]
            for t in self.measure_grid:
                m_num = t.number
                src_m = staff.measure(m_num)
                if m_num in interludes or src_m is None or len(src_m.flatten().notes) == 0:
                    for k in women_keys:
                        results[k].parts[0].append(self._create_rest_measure(t))
                    continue
                has_chords = any(isinstance(n, chord.Chord) for n in src_m.flatten().notes)
                if has_chords:
                    m_up, m_low = self._separate_divisi(src_m, t)
                    for k in ["S1", "S2"]:
                        results[k].parts[0].append(copy.deepcopy(m_up))
                    for k in ["A1", "A2"]:
                        results[k].parts[0].append(copy.deepcopy(m_low))
                else:
                    m_cloned = self._clone_measure(src_m, t)
                    for k in women_keys:
                        results[k].parts[0].append(copy.deepcopy(m_cloned))
        elif n_v == 2:
            self._route_discrete_staff(self.vocal_parts[0], ["S1", "S2"], results, interludes)
            self._route_discrete_staff(self.vocal_parts[1], ["A1", "A2"], results, interludes)
        elif n_v == 3:
            self._route_discrete_staff(self.vocal_parts[0], ["S1"], results, interludes)
            self._route_discrete_staff(self.vocal_parts[1], ["S2"], results, interludes)
            self._route_discrete_staff(self.vocal_parts[2], ["A1", "A2"], results, interludes)
        else:
            self._route_discrete_staff(self.vocal_parts[0], ["S1"], results, interludes)
            self._route_discrete_staff(self.vocal_parts[1], ["S2"], results, interludes)
            self._route_discrete_staff(self.vocal_parts[2], ["A1"], results, interludes)
            self._route_discrete_staff(self.vocal_parts[3], ["A2"], results, interludes)

    def _route_unison_voices(self, results: Dict[str, music21.stream.Score], interludes: set):
        """Routes vocal staves across all 10 vocal parts (S1..B2)."""
        all_vocal_keys = [k for k in STEM_TAXONOMY if k != "Piano"]
        staff = self.vocal_parts[0] if self.vocal_parts else None
        if not staff:
            for k in all_vocal_keys:
                for t in self.measure_grid:
                    results[k].parts[0].append(self._create_rest_measure(t))
            return

        for t in self.measure_grid:
            m_num = t.number
            src_m = staff.measure(m_num)
            if m_num in interludes or src_m is None or len(src_m.flatten().notes) == 0:
                for k in all_vocal_keys:
                    results[k].parts[0].append(self._create_rest_measure(t))
                continue
            m_cloned = self._clone_measure(src_m, t)
            for k in all_vocal_keys:
                results[k].parts[0].append(copy.deepcopy(m_cloned))

    def _separate_divisi(self, src_m: music21.stream.Measure, t: MeasureTemplate) -> Tuple[music21.stream.Measure, music21.stream.Measure]:
        """Separates chordal/polyphonic staff into upper line (Voice 1) and lower line (Voice 2)."""
        m_upper = stream.Measure(number=t.number)
        m_lower = stream.Measure(number=t.number)
        m_upper.timeSignature = meter.TimeSignature(t.time_signature)
        m_lower.timeSignature = meter.TimeSignature(t.time_signature)

        for el in src_m.flatten().notesAndRests:
            if isinstance(el, chord.Chord):
                # Highest pitch to upper, lowest to lower
                pitches = sorted(el.pitches)
                n_up = note.Note(pitches[-1], quarterLength=el.duration.quarterLength)
                n_low = note.Note(pitches[0], quarterLength=el.duration.quarterLength)
                m_upper.insert(el.offset, n_up)
                m_lower.insert(el.offset, n_low)
            elif isinstance(el, note.Note):
                m_upper.insert(el.offset, copy.deepcopy(el))
                m_lower.insert(el.offset, copy.deepcopy(el))
            elif isinstance(el, note.Rest):
                m_upper.insert(el.offset, copy.deepcopy(el))
                m_lower.insert(el.offset, copy.deepcopy(el))

        return m_upper, m_lower

    def _measure_from_voice(self, voice: music21.stream.Voice, t: MeasureTemplate) -> music21.stream.Measure:
        m = stream.Measure(number=t.number)
        m.timeSignature = meter.TimeSignature(t.time_signature)
        for el in voice.flatten().notesAndRests:
            m.insert(el.offset, copy.deepcopy(el))
        return m

    def _clone_measure(self, src_m: music21.stream.Measure, t: MeasureTemplate) -> music21.stream.Measure:
        m = stream.Measure(number=t.number)
        m.timeSignature = meter.TimeSignature(t.time_signature)
        for el in src_m.flatten().notesAndRests:
            m.insert(el.offset, copy.deepcopy(el))
        return m

    def _create_rest_measure(self, t: MeasureTemplate) -> music21.stream.Measure:
        m = stream.Measure(number=t.number)
        m.timeSignature = meter.TimeSignature(t.time_signature)
        m.append(note.Rest(quarterLength=t.quarter_length))
        return m

    def _create_empty_stem(self, stem_name: str) -> music21.stream.Score:
        sc = stream.Score()
        p = stream.Part()
        p.partName = STEM_METADATA.get(stem_name, {}).get("display", stem_name)
        p.id = stem_name
        for t in self.measure_grid:
            p.append(self._create_rest_measure(t))
        sc.append(p)
        return sc

    def _check_solo(self, m: Optional[music21.stream.Measure], m_num: Optional[int] = None) -> Tuple[bool, Optional[str]]:
        if m_num is not None and hasattr(self, "custom_solos") and m_num in self.custom_solos:
            return True, self.custom_solos[m_num]

        if m is not None:
            for text in m.flatten().getElementsByClass(music21.expressions.TextExpression):
                content = (text.content or "").lower()
                if "solo" in content:
                    if "sop" in content:
                        return True, "S"
                    elif "alt" in content:
                        return True, "A"
                    elif "ten" in content:
                        return True, "T"
                    elif "bass" in content or "bar" in content:
                        return True, "B"
                    return True, None
        return False, None

    def _enforce_metric_lockstep(self, stem_name: str, score: music21.stream.Score) -> music21.stream.Score:
        """
        Rule B: Metric Lockstep Synchronization & Duration Clamping.
        - Every measure in all 11 parts sanitized: measure.quarterLength == bar_duration_ql
        - Clamp notes spilling past bar duration due to OMR duration artifacts.
        - Pad underfilled measures with precise rests.
        - Maintain native Fraction tuplet representations.
        """
        part = score.parts[0]
        sanitized_measures = []

        # Set MIDI Program according to taxonomy
        gm_prog = STEM_METADATA.get(stem_name, {}).get("gm_program", 0)
        part.insert(0, music21.instrument.Instrument())
        part.getInstruments()[0].midiProgram = gm_prog

        for i, t in enumerate(self.measure_grid):
            target_ql = t.quarter_length
            m = part.measure(t.number)

            if m is None:
                m = self._create_rest_measure(t)

            # Sanitize measure
            m.number = t.number
            m.timeSignature = meter.TimeSignature(t.time_signature)
            m.insert(0, tempo.MetronomeMark(number=t.tempo_bpm))

            # Collect active elements
            elements = list(m.flatten().notesAndRests)
            elements.sort(key=lambda x: x.offset)

            # Clamping pass
            valid_elements = []
            for el in elements:
                offset_ql = Fraction(el.offset)
                dur_ql = Fraction(el.duration.quarterLength)

                if offset_ql >= target_ql:
                    # Starts after bar end, omit OMR bleed
                    continue
                elif offset_ql + dur_ql > target_ql:
                    # Clamped note
                    clamped_dur = target_ql - offset_ql
                    el.duration = music21.duration.Duration(clamped_dur)
                    valid_elements.append((offset_ql, el))
                else:
                    valid_elements.append((offset_ql, el))

            # Rebuild clean measure
            clean_m = stream.Measure(number=t.number)
            if i == 0 or t.time_signature != self.measure_grid[i - 1].time_signature:
                clean_m.timeSignature = meter.TimeSignature(t.time_signature)
            if i == 0 or t.tempo_bpm != self.measure_grid[i - 1].tempo_bpm:
                clean_m.insert(0, tempo.MetronomeMark(number=t.tempo_bpm))

            if not valid_elements:
                clean_m.append(note.Rest(quarterLength=target_ql))
            else:
                last_end = Fraction(0)
                for off, el in valid_elements:
                    if off > last_end:
                        # Gap before element, fill with rest
                        clean_m.insert(float(last_end), note.Rest(quarterLength=off - last_end))
                    clean_m.insert(float(off), el)
                    last_end = off + Fraction(el.duration.quarterLength)

                if last_end < target_ql:
                    # Measure underfilled, pad with rest
                    clean_m.insert(float(last_end), note.Rest(quarterLength=target_ql - last_end))

            sanitized_measures.append(clean_m)

        # Replace measures in part
        new_part = stream.Part()
        new_part.partName = STEM_METADATA.get(stem_name, {}).get("display", stem_name)
        new_part.id = stem_name
        new_part.insert(0, music21.instrument.Instrument())
        new_part.getInstruments()[0].midiProgram = gm_prog

        for m in sanitized_measures:
            new_part.append(m)

        new_score = stream.Score()
        new_score.append(new_part)
        return new_score

    def _generate_measure_analysis(self, stem_scores: Dict[str, music21.stream.Score]) -> List[Dict[str, Any]]:
        """
        Produces detailed measure analysis:
        - Measure number, start time (s), duration (s), quarter length, meter, tempo.
        - Active parts & resting parts per measure.
        - 'Jump to Next Entrance' markers for resting choristers.
        """
        analysis = []
        prev_active_parts = set()

        for t in self.measure_grid:
            m_num = t.number
            active = []
            resting = []

            for key in STEM_TAXONOMY:
                sc = stem_scores[key]
                m = sc.parts[0].measure(m_num)
                if m is not None:
                    # Has sounding notes?
                    notes = m.flatten().notes
                    if len(notes) > 0:
                        active.append(key)
                    else:
                        resting.append(key)
                else:
                    resting.append(key)

            # Entrances: parts that were resting previously and start here
            entrances = [p for p in active if p not in prev_active_parts]
            prev_active_parts = set(active)

            analysis.append({
                "measure_number": m_num,
                "start_time_seconds": round(t.start_seconds, 3),
                "duration_seconds": round(t.duration_seconds, 3),
                "quarter_length": float(t.quarter_length),
                "time_signature": t.time_signature,
                "tempo_bpm": t.tempo_bpm,
                "active_parts": active,
                "resting_parts": resting,
                "entrances": entrances
            })

        return analysis
