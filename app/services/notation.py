import copy
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import music21 as m21

logger = logging.getLogger("parttrackr.notation")

STANDARD_CHORAL_PARTS = {
    "Piano": "Piano Score",
    "S1": "Soprano I",
    "S2": "Soprano II",
    "A1": "Alto I",
    "A2": "Alto II",
    "T1": "Tenor I",
    "T2": "Tenor II",
    "Bar1": "Baritone I",
    "Bar2": "Baritone II",
    "B1": "Bass I",
    "B2": "Bass II",
}

# Preferred General MIDI instrument mappings for clear rehearsal playback
GM_INSTRUMENTS = {
    "Piano": m21.instrument.Piano(),             # GM 0 - Acoustic Grand Piano
    "S1": m21.instrument.Choir(),                # GM 52 - Choir Aahs
    "S2": m21.instrument.Choir(),
    "A1": m21.instrument.Choir(),
    "A2": m21.instrument.Choir(),
    "T1": m21.instrument.Choir(),
    "T2": m21.instrument.Choir(),
    "Bar1": m21.instrument.Choir(),
    "Bar2": m21.instrument.Choir(),
    "B1": m21.instrument.Choir(),
    "B2": m21.instrument.Choir(),
}


@dataclass
class ExtractedStem:
    part_key: str              # e.g. "S1", "A1", "T1", "B1", "Piano"
    part_name: str             # e.g. "Soprano I", "Piano Score"
    is_accompaniment: bool
    original_part_name: str
    stream: m21.stream.Part
    xml_path: Optional[Path] = None
    midi_path: Optional[Path] = None
    duration_seconds: float = 0.0
    pitch_range: Optional[str] = None
    measure_count: int = 0
    note_count: int = 0


class NotationProcessor:
    """Processes MusicXML scores, splits voices and staves, and normalizes into standard choral stems."""

    def __init__(self):
        pass

    def parse_score(self, file_path: Path) -> m21.stream.Score:
        """Parse MusicXML, MXL, or MIDI score using music21."""
        file_path = Path(file_path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Score file does not exist: {file_path}")

        logger.info("Parsing score file with music21: %s", file_path)
        try:
            score = m21.converter.parse(str(file_path))
            if not isinstance(score, m21.stream.Score):
                # If wrapped in an Op or Part, convert to Score
                wrapped = m21.stream.Score()
                if isinstance(score, m21.stream.Part):
                    wrapped.append(score)
                else:
                    for el in score:
                        wrapped.append(el)
                score = wrapped
            return score
        except Exception as exc:
            logger.error("Failed to parse score %s: %s", file_path, exc)
            raise ValueError(f"Failed to parse music notation file: {exc}")

    def extract_metadata(self, score: m21.stream.Score, fallback_title: str) -> Tuple[str, Optional[str]]:
        """Extract title and composer from score metadata."""
        title = fallback_title
        composer = None
        if score.metadata:
            if score.metadata.title:
                title = score.metadata.title
            elif score.metadata.movementName:
                title = score.metadata.movementName
            if score.metadata.composer:
                composer = score.metadata.composer

        # Clean title
        title = re.sub(r"\.[^.]+$", "", title).strip() or fallback_title
        return title, composer

    def _get_part_search_string(self, part: m21.stream.Part) -> str:
        """Extract clean text representation of part name and instruments without memory ids."""
        tokens = []
        if part.partName:
            tokens.append(str(part.partName))
        if part.partAbbreviation:
            tokens.append(str(part.partAbbreviation))
        if not tokens and part.id and not str(part.id).isdigit():
            tokens.append(str(part.id))

        for inst in part.getInstruments():
            if inst.instrumentName:
                tokens.append(str(inst.instrumentName))
            if inst.instrumentAbbreviation:
                tokens.append(str(inst.instrumentAbbreviation))

        return " ".join(tokens).lower()

    def is_accompaniment_part(self, part: m21.stream.Part) -> bool:
        """Determine if a part is piano or instrumental accompaniment."""
        name_str = self._get_part_search_string(part)
        keywords = [
            "piano", "pno", "klavier", "organ", "org", "accomp", "acc.", "acc",
            "keyboard", "cembalo", "harpsichord", "reduction", "continuo", "orch"
        ]
        return any(kw in name_str for kw in keywords)

    def identify_part_category(self, part: m21.stream.Part) -> str:
        """
        Classifies a part into raw categories:
        'piano', 'soprano', 'alto', 'tenor', 'baritone', 'bass',
        'soprano_alto', 'tenor_bass', 's1', 's2', 'a1', 'a2', 't1', 't2', 'bar1', 'b1', 'b2',
        or 'unknown'.
        """
        if self.is_accompaniment_part(part):
            return "piano"

        name_str = self._get_part_search_string(part)

        # Check combined staves first
        if any(term in name_str for term in ["soprano & alto", "soprano/alto", "s/a", "sa", "women", "treble 1 & 2"]):
            return "soprano_alto"
        if any(term in name_str for term in ["tenor & bass", "tenor/bass", "t/b", "tb", "men"]):
            return "tenor_bass"

        # Check specific numbered parts with strict word boundaries
        if re.search(r"\bsoprano\s*(1|i)\b|\bs\s*1\b|\bdescant\b", name_str):
            return "s1"
        if re.search(r"\bsoprano\s*(2|ii)\b|\bs\s*2\b|\bmezzo\b", name_str):
            return "s2"
        if re.search(r"\bsoprano\b|\bsopr\b|\bcantus\b|\btreble\b", name_str):
            return "soprano"

        if re.search(r"\balto\s*(1|i)\b|\ba\s*1\b|\bcontralto\s*(1|i)\b", name_str):
            return "a1"
        if re.search(r"\balto\s*(2|ii)\b|\ba\s*2\b|\bcontralto\s*(2|ii)\b", name_str):
            return "a2"
        if re.search(r"\balto\b|\baltus\b|\bcontralto\b", name_str):
            return "alto"

        if re.search(r"\btenor\s*(1|i)\b|\bt\s*1\b", name_str):
            return "t1"
        if re.search(r"\btenor\s*(2|ii)\b|\bt\s*2\b", name_str):
            return "t2"
        if re.search(r"\btenor\b", name_str):
            return "tenor"

        if re.search(r"\bbaritone\s*(1|i)\b|\bbar\s*1\b", name_str):
            return "bar1"
        if re.search(r"\bbaritone\s*(2|ii)\b|\bbar\s*2\b", name_str):
            return "bar2"
        if re.search(r"\bbaritone\b|\bbar\b", name_str):
            return "baritone"

        if re.search(r"\bbass\s*(1|i)\b|\bb\s*1\b|\bbasso\s*(1|i)\b", name_str):
            return "b1"
        if re.search(r"\bbass\s*(2|ii)\b|\bb\s*2\b|\bbasso\s*(2|ii)\b", name_str):
            return "b2"
        if re.search(r"\bbass\b|\bbasso\b", name_str):
            return "bass"

        return "unknown"

    def split_polyphonic_staff(
        self, part: m21.stream.Part, upper_label: str, lower_label: str
    ) -> Tuple[m21.stream.Part, m21.stream.Part]:
        """
        Splits a shared choral staff (e.g. Soprano & Alto or Tenor & Bass) into two independent parts
        by analyzing voice numbers, stem directions, and chord divisi.
        """
        upper_part = m21.stream.Part()
        upper_part.partName = upper_label
        upper_part.id = f"{upper_label.replace(' ', '_')}"

        lower_part = m21.stream.Part()
        lower_part.partName = lower_label
        lower_part.id = f"{lower_label.replace(' ', '_')}"

        measures = part.getElementsByClass(m21.stream.Measure)
        if not measures:
            # Fallback if no measures found
            return copy.deepcopy(part), copy.deepcopy(part)

        for m in measures:
            up_m = m21.stream.Measure(number=m.number)
            low_m = m21.stream.Measure(number=m.number)

            # Copy time signature, key signature, clef if present
            for header_el in m.getElementsByClass([m21.meter.TimeSignature, m21.key.KeySignature, m21.clef.Clef]):
                up_m.append(copy.deepcopy(header_el))
                low_m.append(copy.deepcopy(header_el))

            # Inspect voices
            voices = m.voices
            if len(voices) >= 2:
                # Direct voice separation: voice 1 to upper, voice 2 to lower
                for el in voices[0]:
                    if isinstance(el, (m21.note.Note, m21.chord.Chord, m21.note.Rest)):
                        up_m.append(copy.deepcopy(el))
                for el in voices[1]:
                    if isinstance(el, (m21.note.Note, m21.chord.Chord, m21.note.Rest)):
                        low_m.append(copy.deepcopy(el))
            else:
                # Stem directions and chords
                notes_and_chords = m.getElementsByClass([m21.note.Note, m21.chord.Chord, m21.note.Rest])
                for el in notes_and_chords:
                    if isinstance(el, m21.note.Rest):
                        up_m.append(copy.deepcopy(el))
                        low_m.append(copy.deepcopy(el))
                    elif isinstance(el, m21.chord.Chord):
                        pitches = sorted(el.pitches)
                        if len(pitches) >= 2:
                            # Upper note
                            up_n = m21.note.Note(pitches[-1], quarterLength=el.quarterLength)
                            up_n.offset = el.offset
                            up_m.append(up_n)
                            # Lower note
                            low_n = m21.note.Note(pitches[0], quarterLength=el.quarterLength)
                            low_n.offset = el.offset
                            low_m.append(low_n)
                        else:
                            up_m.append(copy.deepcopy(el))
                            low_m.append(copy.deepcopy(el))
                    elif isinstance(el, m21.note.Note):
                        if el.stemDirection == "up":
                            up_m.append(copy.deepcopy(el))
                        elif el.stemDirection == "down":
                            low_m.append(copy.deepcopy(el))
                        else:
                            # Both sing in unison if no stem direction specified
                            up_m.append(copy.deepcopy(el))
                            low_m.append(copy.deepcopy(el))

            upper_part.append(up_m)
            lower_part.append(low_m)

        return upper_part, lower_part

    def check_for_divisi_chords(self, part: m21.stream.Part) -> bool:
        """Check if a staff has significant chord divisi (more than 15% chords)."""
        notes = list(part.recurse().getElementsByClass([m21.note.Note, m21.chord.Chord]))
        if not notes:
            return False
        chord_count = sum(1 for n in notes if isinstance(n, m21.chord.Chord))
        return (chord_count / len(notes)) >= 0.15

    def split_choral_divisi(
        self, part: m21.stream.Part, part_name_1: str, part_name_2: str
    ) -> Tuple[m21.stream.Part, m21.stream.Part]:
        """Split a part into divisi 1 and 2 when chords or multiple voices occur."""
        return self.split_polyphonic_staff(part, part_name_1, part_name_2)

    def guess_register_from_notes(self, part: m21.stream.Part) -> str:
        """Guess vocal register from average pitch and clef."""
        pitches = [n.pitch.midi for n in part.recurse().notes if hasattr(n, "pitch")]
        if not pitches:
            # Fallback based on clef
            clefs = list(part.recurse().getElementsByClass(m21.clef.Clef))
            if clefs and isinstance(clefs[0], m21.clef.BassClef):
                return "bass"
            return "soprano"

        avg_pitch = sum(pitches) / len(pitches)
        # MIDI note numbers:
        # C4 = 60, C5 = 72, C3 = 48, C2 = 36
        if avg_pitch >= 68:      # ~G#4 and above
            return "soprano"
        elif avg_pitch >= 60:    # ~C4 to G4
            return "alto"
        elif avg_pitch >= 52:    # ~E3 to B3
            return "tenor"
        elif avg_pitch >= 45:    # ~A2 to D#3
            return "baritone"
        else:
            return "bass"

    def combine_piano_staves(self, parts: List[m21.stream.Part]) -> m21.stream.Part:
        """Combine multiple accompaniment parts (e.g. RH + LH) into a single Piano Score part."""
        if len(parts) == 1:
            res = copy.deepcopy(parts[0])
            res.partName = "Piano Score"
            res.id = "Piano"
            return res

        combined = m21.stream.Part()
        combined.partName = "Piano Score"
        combined.id = "Piano"

        # Merge measures by measure number
        measure_nums = set()
        for p in parts:
            for m in p.getElementsByClass(m21.stream.Measure):
                measure_nums.add(m.number)

        for m_num in sorted(measure_nums):
            new_m = m21.stream.Measure(number=m_num)
            for p in parts:
                p_m = p.measure(m_num)
                if p_m:
                    for el in p_m:
                        if not isinstance(el, (m21.meter.TimeSignature, m21.key.KeySignature)):
                            new_m.append(copy.deepcopy(el))
            combined.append(new_m)

        return combined

    def process_and_extract_stems(
        self, score: m21.stream.Score, output_xml_dir: Path, output_midi_dir: Path
    ) -> List[ExtractedStem]:
        """
        Splits and normalizes the score into standard choral parts and Piano Score:
        - Soprano I, Soprano II
        - Alto I, Alto II
        - Tenor I, Tenor II
        - Baritone I, Baritone II
        - Bass I, Bass II
        - Piano Score

        Aggregates/collapses SATB, SAB, SSA, TTBB cleanly without failing.
        Exports individual XML and MIDI for each stem.
        """
        output_xml_dir.mkdir(parents=True, exist_ok=True)
        output_midi_dir.mkdir(parents=True, exist_ok=True)

        extracted_raw: Dict[str, List[m21.stream.Part]] = {
            "piano": [],
            "s1": [],
            "s2": [],
            "soprano": [],
            "a1": [],
            "a2": [],
            "alto": [],
            "t1": [],
            "t2": [],
            "tenor": [],
            "bar1": [],
            "bar2": [],
            "baritone": [],
            "b1": [],
            "b2": [],
            "bass": [],
            "unknown": [],
        }

        # Step 1: Classify existing parts
        for part in score.parts:
            cat = self.identify_part_category(part)
            if cat == "soprano_alto":
                up, low = self.split_polyphonic_staff(part, "Soprano", "Alto")
                extracted_raw["soprano"].append(up)
                extracted_raw["alto"].append(low)
            elif cat == "tenor_bass":
                up, low = self.split_polyphonic_staff(part, "Tenor", "Bass")
                extracted_raw["tenor"].append(up)
                extracted_raw["bass"].append(low)
            elif cat in extracted_raw:
                extracted_raw[cat].append(part)
            else:
                extracted_raw["unknown"].append(part)

        # Step 2: Handle unknowns by register
        if extracted_raw["unknown"]:
            for p in extracted_raw["unknown"]:
                reg = self.guess_register_from_notes(p)
                extracted_raw[reg].append(p)

        # Step 3: Handle divisi and collapse into standard 11 parts
        final_parts: Dict[str, Tuple[str, bool, m21.stream.Part, str]] = {}
        # Key: stem_key (e.g. "S1", "Piano")
        # Value: (part_name, is_accompaniment, stream, original_part_name)

        # --- Piano / Accompaniment ---
        if extracted_raw["piano"]:
            piano_stream = self.combine_piano_staves(extracted_raw["piano"])
            final_parts["Piano"] = ("Piano Score", True, piano_stream, "Accompaniment")

        # --- Sopranos ---
        s_parts = extracted_raw["s1"] + extracted_raw["soprano"]
        s2_parts = extracted_raw["s2"]
        if s_parts and s2_parts:
            final_parts["S1"] = ("Soprano I", False, s_parts[0], s_parts[0].partName or "Soprano 1")
            final_parts["S2"] = ("Soprano II", False, s2_parts[0], s2_parts[0].partName or "Soprano 2")
        elif len(s_parts) >= 2:
            final_parts["S1"] = ("Soprano I", False, s_parts[0], s_parts[0].partName or "Soprano 1")
            final_parts["S2"] = ("Soprano II", False, s_parts[1], s_parts[1].partName or "Soprano 2")
        elif s2_parts and not s_parts:
            final_parts["S2"] = ("Soprano II", False, s2_parts[0], s2_parts[0].partName or "Soprano 2")
        elif len(s_parts) == 1:
            # Check if this single Soprano staff has divisi chords
            if self.check_for_divisi_chords(s_parts[0]):
                s1, s2 = self.split_choral_divisi(s_parts[0], "Soprano I", "Soprano II")
                final_parts["S1"] = ("Soprano I", False, s1, "Soprano (Divisi 1)")
                final_parts["S2"] = ("Soprano II", False, s2, "Soprano (Divisi 2)")
            else:
                final_parts["S1"] = ("Soprano I", False, s_parts[0], s_parts[0].partName or "Soprano")

        # --- Altos ---
        a_parts = extracted_raw["a1"] + extracted_raw["alto"]
        a2_parts = extracted_raw["a2"]
        if a_parts and a2_parts:
            final_parts["A1"] = ("Alto I", False, a_parts[0], a_parts[0].partName or "Alto 1")
            final_parts["A2"] = ("Alto II", False, a2_parts[0], a2_parts[0].partName or "Alto 2")
        elif len(a_parts) >= 2:
            final_parts["A1"] = ("Alto I", False, a_parts[0], a_parts[0].partName or "Alto 1")
            final_parts["A2"] = ("Alto II", False, a_parts[1], a_parts[1].partName or "Alto 2")
        elif a2_parts and not a_parts:
            final_parts["A2"] = ("Alto II", False, a2_parts[0], a2_parts[0].partName or "Alto 2")
        elif len(a_parts) == 1:
            if self.check_for_divisi_chords(a_parts[0]):
                a1, a2 = self.split_choral_divisi(a_parts[0], "Alto I", "Alto II")
                final_parts["A1"] = ("Alto I", False, a1, "Alto (Divisi 1)")
                final_parts["A2"] = ("Alto II", False, a2, "Alto (Divisi 2)")
            else:
                final_parts["A1"] = ("Alto I", False, a_parts[0], a_parts[0].partName or "Alto")

        # --- Tenors ---
        t_parts = extracted_raw["t1"] + extracted_raw["tenor"]
        t2_parts = extracted_raw["t2"]
        if t_parts and t2_parts:
            final_parts["T1"] = ("Tenor I", False, t_parts[0], t_parts[0].partName or "Tenor 1")
            final_parts["T2"] = ("Tenor II", False, t2_parts[0], t2_parts[0].partName or "Tenor 2")
        elif len(t_parts) >= 2:
            final_parts["T1"] = ("Tenor I", False, t_parts[0], t_parts[0].partName or "Tenor 1")
            final_parts["T2"] = ("Tenor II", False, t_parts[1], t_parts[1].partName or "Tenor 2")
        elif t2_parts and not t_parts:
            final_parts["T2"] = ("Tenor II", False, t2_parts[0], t2_parts[0].partName or "Tenor 2")
        elif len(t_parts) == 1:
            if self.check_for_divisi_chords(t_parts[0]):
                t1, t2 = self.split_choral_divisi(t_parts[0], "Tenor I", "Tenor II")
                final_parts["T1"] = ("Tenor I", False, t1, "Tenor (Divisi 1)")
                final_parts["T2"] = ("Tenor II", False, t2, "Tenor (Divisi 2)")
            else:
                final_parts["T1"] = ("Tenor I", False, t_parts[0], t_parts[0].partName or "Tenor")

        # --- Baritones ---
        bar_parts = extracted_raw["bar1"] + extracted_raw["baritone"]
        bar2_parts = extracted_raw["bar2"]
        if bar_parts and bar2_parts:
            final_parts["Bar1"] = ("Baritone I", False, bar_parts[0], bar_parts[0].partName or "Baritone 1")
            final_parts["Bar2"] = ("Baritone II", False, bar2_parts[0], bar2_parts[0].partName or "Baritone 2")
        elif len(bar_parts) >= 2:
            final_parts["Bar1"] = ("Baritone I", False, bar_parts[0], bar_parts[0].partName or "Baritone 1")
            final_parts["Bar2"] = ("Baritone II", False, bar2_parts[0], bar2_parts[0].partName or "Baritone 2")
        elif bar2_parts and not bar_parts:
            final_parts["Bar2"] = ("Baritone II", False, bar2_parts[0], bar2_parts[0].partName or "Baritone 2")
        elif len(bar_parts) == 1:
            final_parts["Bar1"] = ("Baritone I", False, bar_parts[0], bar_parts[0].partName or "Baritone")

        # --- Basses ---
        b_parts = extracted_raw["b1"] + extracted_raw["bass"]
        b2_parts = extracted_raw["b2"]
        if b_parts and b2_parts:
            final_parts["B1"] = ("Bass I", False, b_parts[0], b_parts[0].partName or "Bass 1")
            final_parts["B2"] = ("Bass II", False, b2_parts[0], b2_parts[0].partName or "Bass 2")
        elif len(b_parts) >= 2:
            final_parts["B1"] = ("Bass I", False, b_parts[0], b_parts[0].partName or "Bass 1")
            final_parts["B2"] = ("Bass II", False, b_parts[1], b_parts[1].partName or "Bass 2")
        elif b2_parts and not b_parts:
            final_parts["B2"] = ("Bass II", False, b2_parts[0], b2_parts[0].partName or "Bass 2")
        elif len(b_parts) == 1:
            if self.check_for_divisi_chords(b_parts[0]):
                b1, b2 = self.split_choral_divisi(b_parts[0], "Bass I", "Bass II")
                final_parts["B1"] = ("Bass I", False, b1, "Bass (Divisi 1)")
                final_parts["B2"] = ("Bass II", False, b2, "Bass (Divisi 2)")
            else:
                final_parts["B1"] = ("Bass I", False, b_parts[0], b_parts[0].partName or "Bass")

        # Fallback safeguard: if no vocal parts were mapped at all, use score parts directly
        if not any(k != "Piano" for k in final_parts.keys()) and score.parts:
            for idx, p in enumerate(score.parts):
                key = ["S1", "A1", "T1", "B1"][idx % 4]
                name = STANDARD_CHORAL_PARTS[key]
                final_parts[key] = (name, False, p, p.partName or f"Part {idx+1}")

        # Extract master tempo mark if available
        tempo_marks = list(score.recurse().getElementsByClass(m21.tempo.MetronomeMark))
        master_tempo = tempo_marks[0] if tempo_marks else m21.tempo.MetronomeMark(number=100)

        # Step 4: Export stems to MIDI & MusicXML
        stems_result: List[ExtractedStem] = []

        # Order parts logically: Piano first, then S1, S2, A1, A2, T1, T2, Bar1, Bar2, B1, B2
        sort_order = ["Piano", "S1", "S2", "A1", "A2", "T1", "T2", "Bar1", "Bar2", "B1", "B2"]
        sorted_keys = sorted(
            final_parts.keys(),
            key=lambda k: sort_order.index(k) if k in sort_order else 99
        )

        for key in sorted_keys:
            part_name, is_acc, stream_part, orig_name = final_parts[key]
            stream_part = copy.deepcopy(stream_part)
            stream_part.partName = part_name
            stream_part.id = key

            # Assign GM Instrument
            gm_inst = GM_INSTRUMENTS.get(key, m21.instrument.Choir())
            stream_part.insert(0, copy.deepcopy(gm_inst))

            # Ensure tempo is present in first measure
            first_m = stream_part.measure(1)
            if first_m:
                if not first_m.getElementsByClass(m21.tempo.MetronomeMark):
                    first_m.insert(0, copy.deepcopy(master_tempo))
            else:
                stream_part.insert(0, copy.deepcopy(master_tempo))

            # Calculate metadata: pitch range, measure count, note count
            notes = list(stream_part.recurse().notes)
            note_count = len(notes)
            measure_count = len(stream_part.getElementsByClass(m21.stream.Measure))

            pitch_range = None
            pitches = [n.pitch for n in notes if hasattr(n, "pitch")]
            for chord in [n for n in notes if isinstance(n, m21.chord.Chord)]:
                pitches.extend(chord.pitches)

            if pitches:
                sorted_pitches = sorted(pitches, key=lambda p: p.midi)
                pitch_range = f"{sorted_pitches[0].nameWithOctave} - {sorted_pitches[-1].nameWithOctave}"

            # Calculate duration in seconds
            # total quarterLength / (tempo_bpm / 60)
            bpm = master_tempo.number if (master_tempo and master_tempo.number) else 100
            total_ql = stream_part.highestTime
            duration_sec = (total_ql / (bpm / 60.0)) if bpm > 0 else total_ql * 0.6
            duration_sec = round(max(1.0, duration_sec), 2)

            stem_obj = ExtractedStem(
                part_key=key,
                part_name=part_name,
                is_accompaniment=is_acc,
                original_part_name=orig_name,
                stream=stream_part,
                duration_seconds=duration_sec,
                pitch_range=pitch_range,
                measure_count=measure_count,
                note_count=note_count,
            )

            # Export standalone MusicXML
            xml_filename = f"stem_{key}.musicxml"
            xml_path = output_xml_dir / xml_filename
            try:
                stream_part.write("musicxml", fp=str(xml_path))
                stem_obj.xml_path = xml_path
            except Exception as e:
                logger.warning("Could not write MusicXML for stem %s: %s", key, e)

            # Export standalone MIDI
            midi_filename = f"stem_{key}.mid"
            midi_path = output_midi_dir / midi_filename
            try:
                # Wrap part in a single-part score to ensure proper MIDI header and tempo
                stem_score = m21.stream.Score()
                stem_score.append(stream_part)
                stem_score.write("midi", fp=str(midi_path))
                stem_obj.midi_path = midi_path
            except Exception as e:
                logger.error("Could not write MIDI for stem %s: %s", key, e)

            stems_result.append(stem_obj)
            logger.info(
                "Extracted stem: key=%s, name='%s', notes=%d, duration=%.1fs, range=%s",
                key, part_name, note_count, duration_sec, pitch_range
            )

        return stems_result


notation_processor = NotationProcessor()
