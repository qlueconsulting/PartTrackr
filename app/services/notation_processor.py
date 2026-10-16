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

    def __init__(self, score_path: Path):
        self.score_path = score_path
        self.raw_score: music21.stream.Score = music21.converter.parse(str(score_path))
        self.title = self._extract_title()
        self.composer = self._extract_composer()
        
        # Identified parts
        self.accomp_parts: List[music21.stream.Part] = []
        self.vocal_parts: List[music21.stream.Part] = []
        self._classify_staves()
        
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

            if is_brace:
                self.accomp_parts.append(part)
            elif is_bracket or has_lyrics:
                self.vocal_parts.append(part)
            elif any(k in combined_name for k in accomp_keywords):
                self.accomp_parts.append(part)
            elif any(k in combined_name for k in vocal_keywords):
                self.vocal_parts.append(part)
            else:
                # Default heuristic: if 4+ staves and bottom 2 don't have lyrics, bottom 2 are piano
                self.vocal_parts.append(part)

        # If no accompaniment detected yet but we have >= 3 parts and bottom 2 have no lyrics, treat bottom 2 as piano
        if not self.accomp_parts and len(all_parts) >= 3:
            candidate_bottom = all_parts[-2:]
            if not any(any(bool(n.lyrics) for n in p.flatten().notes) for p in candidate_bottom):
                self.accomp_parts = list(candidate_bottom)
                self.vocal_parts = [p for p in all_parts if p not in self.accomp_parts]

    def _build_foundational_measure_grid(self):
        """
        Rule A1a: Always start with the accompaniment (if available) to give a basis 
        for measure counts, and then apply the other parts onto the foundational measure structure.
        """
        # Determine source stream for foundational grid
        source_parts = self.accomp_parts if self.accomp_parts else self.vocal_parts
        if not source_parts:
            source_parts = list(self.raw_score.parts)

        # Gather all unique measure numbers across parts
        measure_numbers = []
        for p in source_parts:
            m_nums = [m.number for m in p.getElementsByClass(stream.Measure)]
            if len(m_nums) > len(measure_numbers):
                measure_numbers = m_nums

        if not measure_numbers:
            # Fallback if unmeasured
            measure_numbers = [1]

        # Determine time signatures and tempos
        current_ts = meter.TimeSignature("4/4")
        current_tempo = 120.0

        # Scan for initial time signature or tempo in score
        first_ts = self.raw_score.flatten().getElementsByClass(meter.TimeSignature).first()
        if first_ts:
            current_ts = first_ts
        first_tempo = self.raw_score.flatten().getElementsByClass(tempo.MetronomeMark).first()
        if first_tempo and first_tempo.number:
            current_tempo = float(first_tempo.number)

        cumulative_seconds = 0.0

        for m_num in measure_numbers:
            # Check if any part defines a new TS or tempo at this measure
            for p in source_parts:
                m = p.measure(m_num)
                if m is not None:
                    ts = m.getElementsByClass(meter.TimeSignature).first()
                    if ts:
                        current_ts = ts
                    tm = m.getElementsByClass(tempo.MetronomeMark).first()
                    if tm and tm.number:
                        current_tempo = float(tm.number)
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

        if n_vocal == 0:
            # No vocal staves (pure instrumental score), all vocal parts rest
            for k in results:
                for t in self.measure_grid:
                    m = self._create_rest_measure(t)
                    results[k].parts[0].append(m)
            return results

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
            is_solo, solo_target = self._check_solo(src_m)

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
        """Heuristic mapping for non-standard choral staff layouts."""
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
                # Distribute evenly
                targets = ["S1", "A1", "T1", "B1"]
                t = targets[min(i, len(targets) - 1)]
                self._route_discrete_staff(p, [t], results, interludes)

        # Fill any unassigned stems with rests
        for k in results:
            while len(results[k].parts[0].getElementsByClass(stream.Measure)) < len(self.measure_grid):
                idx = len(results[k].parts[0].getElementsByClass(stream.Measure))
                results[k].parts[0].append(self._create_rest_measure(self.measure_grid[idx]))

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

    def _check_solo(self, m: music21.stream.Measure) -> Tuple[bool, Optional[str]]:
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
