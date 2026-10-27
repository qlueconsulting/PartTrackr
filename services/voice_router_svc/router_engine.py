import copy
import logging
from typing import Dict, List, Tuple, Any, Optional
from common.taxonomy import CANONICAL_11_PARTS, PART_METADATA
from common.cism_schema import (
    ScoreCISM,
    SystemData,
    MeasureData,
    StaffInfo,
    TrackData,
    NoteElement,
)
from common.lockstep_utils import reconcile_cism_measures
from common.music_theory_engine import MusicTheoryEngine

logger = logging.getLogger("voice_router_svc")


class VoiceRouterEngine:
    """
    Ingests Raw CISM JSON and normalizes staves into the 11 canonical rehearsal parts:
    soprano_1, soprano_2, alto_1, alto_2, tenor_1, tenor_2, baritone_1, baritone_2, bass_1, bass_2, piano.
    Applies unison duplication, divisi splitting, accompaniment anchoring, and interlude suppression.
    """

    @classmethod
    def _is_definitely_vocal_staff(cls, st: StaffInfo, sys: SystemData) -> bool:
        """Determines if a staff is unequivocally a vocal part via lyrics, vocal labels, or choral brackets."""
        if st.has_lyrics:
            return True
        for m in sys.measures:
            raw_t = m.raw_staves.get(st.staff_id)
            if raw_t:
                for el in raw_t.elements:
                    if el.lyric and el.lyric.strip():
                        return True

        lbl = (st.label or "").lower()
        vocal_keywords = (
            "soprano", "alto", "tenor", "baritone", "bass",
            "choir", "chorus", "women", "men", "voices",
            "s.", "a.", "t.", "b.", "s1", "s2", "a1", "a2", "t1", "t2", "b1", "b2",
            "solo", "cantor", "unison", "congregation"
        )
        if any(k in lbl for k in vocal_keywords):
            return True

        if st.bracket_type == "bracket":
            return True

        return False

    @classmethod
    def _is_definitely_piano_staff(cls, st: StaffInfo) -> bool:
        """Determines if a staff is unequivocally an accompaniment staff via brace, role, or label."""
        if st.bracket_type == "brace" or st.role in ("piano_rh", "piano_lh"):
            return True
        lbl = (st.label or "").lower()
        piano_keywords = ("piano", "keyboard", "pno", "organ", "org", "pianoforte", "accomp")
        if any(k in lbl for k in piano_keywords):
            return True
        return False

    @classmethod
    def route_score(
        cls,
        cism: ScoreCISM,
        overrides: Optional[Dict[str, Any]] = None,
        score_hints: Optional[Dict[str, Any]] = None
    ) -> ScoreCISM:
        cism_out = cism.model_copy(deep=True)

        target_measures = score_hints.get("total_measures") if score_hints else None
        target_ts = score_hints.get("time_signature") if score_hints else None
        target_bpm = score_hints.get("tempo_bpm") if score_hints else None
        accompaniment_type = score_hints.get("accompaniment_type") if score_hints else None

        has_piano = None
        if accompaniment_type == "a_cappella":
            has_piano = False
        elif accompaniment_type in ("piano", "orchestra_reduction"):
            has_piano = True

        if target_measures:
            cism_out = reconcile_cism_measures(
                cism_out,
                target_total_measures=int(target_measures),
                target_time_signature=target_ts,
                target_tempo_bpm=target_bpm,
                has_piano=has_piano
            )
        elif has_piano is not None:
            cism_out.has_piano = has_piano

        for sys in cism_out.systems:
            vocal_staves: List[StaffInfo] = []
            piano_staves: List[StaffInfo] = []

            # Tier 1: Lyric-Anchored Staff Exclusion
            # Staves with lyrics or vocal labels can NEVER be assigned to piano
            vocal_ids = {
                st.staff_id for st in sys.staves if cls._is_definitely_vocal_staff(st, sys)
            }
            piano_ids = {
                st.staff_id for st in sys.staves if cls._is_definitely_piano_staff(st) and st.staff_id not in vocal_ids
            }

            if piano_ids:
                for st in sys.staves:
                    if st.staff_id in piano_ids:
                        piano_staves.append(st)
                    else:
                        vocal_staves.append(st)
            elif cism_out.has_piano and len(sys.staves) >= 3:
                # Bottom 2 non-vocal staves anchor to piano Grand Staff
                bottom_candidates = [st for st in sys.staves[-2:] if st.staff_id not in vocal_ids]
                if len(bottom_candidates) == 2:
                    piano_staves = sys.staves[-2:]
                    vocal_staves = sys.staves[:-2]
                else:
                    # Bottom staves have vocal lyrics! System is a cappella or vocal-only
                    vocal_staves = list(sys.staves)
                    piano_staves = []
            elif cism_out.has_piano and len(sys.staves) == 2:
                if not vocal_ids:
                    piano_staves = list(sys.staves)
                    vocal_staves = []
                else:
                    vocal_staves = list(sys.staves)
                    piano_staves = []
            else:
                vocal_staves = list(sys.staves)
                piano_staves = []

            # Hard Rule: If piano part exists, it is ALWAYS exactly two staves (RH Treble + LH Bass)
            if len(piano_staves) > 2:
                piano_staves = piano_staves[-2:]

            # Order staves top-to-bottom by vertical position for rock-solid voice leading
            vocal_staves.sort(key=lambda s: s.y_top)
            piano_staves.sort(key=lambda s: s.y_top)

            for m in sys.measures:
                m.tracks = cls._route_measure(
                    m=m,
                    vocal_staves=vocal_staves,
                    piano_staves=piano_staves,
                    has_piano_in_score=cism_out.has_piano,
                    overrides=overrides,
                    score_hints=score_hints
                )

        return cism_out

    @classmethod
    def _route_measure(
        cls,
        m: MeasureData,
        vocal_staves: List[StaffInfo],
        piano_staves: List[StaffInfo],
        has_piano_in_score: bool,
        overrides: Optional[Dict[str, Any]],
        score_hints: Optional[Dict[str, Any]] = None
    ) -> Dict[str, TrackData]:
        tracks: Dict[str, TrackData] = {}
        for p in CANONICAL_11_PARTS:
            tracks[p] = TrackData(
                track_name=p,
                clef=PART_METADATA[p]["default_clef"],
                elements=[]
            )

        # 1. Route Piano Accompaniment (Rule A1a & Rule A5)
        # Dedicated RH (Treble) and LH (Bass) staves for Grand Staff MusicXML transcription
        rh_elements: List[NoteElement] = []
        lh_elements: List[NoteElement] = []

        if piano_staves and has_piano_in_score:
            pst_rh = next((pst for pst in piano_staves if pst.role == "piano_rh"), piano_staves[0])
            pst_lh = next((pst for pst in piano_staves if pst.role == "piano_lh"), piano_staves[-1] if len(piano_staves) > 1 else None)

            raw_rh = m.raw_staves.get(pst_rh.staff_id) if pst_rh else None
            raw_lh = m.raw_staves.get(pst_lh.staff_id) if pst_lh else None

            if raw_rh and raw_rh.elements:
                rh_elements = copy.deepcopy(raw_rh.elements)
            if raw_lh and raw_lh.elements:
                lh_elements = copy.deepcopy(raw_lh.elements)

        # If only one staff had all notes, split into RH (>= C4) and LH (< C4)
        if not rh_elements and lh_elements:
            rh_cands = [el for el in lh_elements if (not el.is_rest and (el.midi_pitch or 60) >= 60)]
            lh_cands = [el for el in lh_elements if (not el.is_rest and (el.midi_pitch or 60) < 60)]
            if rh_cands:
                rh_elements = rh_cands
                lh_elements = lh_cands
        elif rh_elements and not lh_elements:
            rh_cands = [el for el in rh_elements if (not el.is_rest and (el.midi_pitch or 60) >= 60)]
            lh_cands = [el for el in rh_elements if (not el.is_rest and (el.midi_pitch or 60) < 60)]
            if lh_cands:
                rh_elements = rh_cands
                lh_elements = lh_cands

        # Clean octave separation: Treble staff (piano_rh) holds notes >= C4 (MIDI 60),
        # Bass staff (piano_lh) holds notes < C4 (MIDI 60). Eliminates cross-staff bleed and distorted octaves.
        if rh_elements or lh_elements:
            cleaned_rh: List[NoteElement] = []
            cleaned_lh: List[NoteElement] = []
            for el in rh_elements:
                if el.is_rest or not el.pitch:
                    continue
                mp = el.midi_pitch or MusicTheoryEngine.pitch_to_midi(el.pitch)
                if mp >= 60:
                    cleaned_rh.append(el)
                else:
                    cleaned_lh.append(el)

            for el in lh_elements:
                if el.is_rest or not el.pitch:
                    continue
                mp = el.midi_pitch or MusicTheoryEngine.pitch_to_midi(el.pitch)
                if mp < 60:
                    cleaned_lh.append(el)
                else:
                    cleaned_rh.append(el)

            rh_elements = cleaned_rh
            lh_elements = cleaned_lh

        whole_rest = [NoteElement(pitch=None, duration_quarters=m.quarter_length, duration_type="whole", offset_quarters=0.0, is_rest=True)]

        tracks["piano_rh"] = TrackData(
            track_name="piano_rh",
            clef="treble",
            elements=rh_elements if rh_elements else whole_rest
        )
        tracks["piano_lh"] = TrackData(
            track_name="piano_lh",
            clef="bass",
            elements=lh_elements if lh_elements else whole_rest
        )
        # Unified piano track for 11-part compatibility & MIDI
        combined_elements = rh_elements + lh_elements
        tracks["piano"] = TrackData(
            track_name="piano",
            clef="grand",
            elements=combined_elements if combined_elements else whole_rest
        )

        # 2. Check if this measure is an instrumental interlude (no vocal notes on raw staves)
        has_vocal_notes = False
        for vst in vocal_staves:
            raw_t = m.raw_staves.get(vst.staff_id)
            if raw_t and any(not el.is_rest for el in raw_t.elements):
                has_vocal_notes = True
                break

        if not has_vocal_notes:
            # All 10 vocal parts rest cleanly
            for p in CANONICAL_11_PARTS:
                if p != "piano":
                    tracks[p].elements = [
                        NoteElement(pitch=None, duration_quarters=m.quarter_length, duration_type="whole", offset_quarters=0.0, is_rest=True)
                    ]
            return tracks

        # 3. Route Vocal Staves based on active vocal topology
        nv = len(vocal_staves)
        if nv == 1:
            cls._route_single_vocal_staff(vocal_staves[0], m, tracks, score_hints=score_hints)
        elif nv == 2:
            cls._route_two_vocal_staves(vocal_staves[0], vocal_staves[1], m, tracks)
        elif nv >= 4:
            cls._route_four_vocal_staves(vocal_staves[:4], m, tracks)
        else:
            cls._route_three_vocal_staves(vocal_staves, m, tracks)

        # 4. Apply any explicit measure-level routing overrides from the UI
        if overrides and str(m.measure_number) in overrides:
            m_override = overrides[str(m.measure_number)]
            for track_k, track_v in m_override.get("tracks", {}).items():
                if track_k in tracks:
                    tracks[track_k] = TrackData(**track_v)

        return tracks

    @classmethod
    def _route_single_vocal_staff(
        cls,
        st: StaffInfo,
        m: MeasureData,
        tracks: Dict[str, TrackData],
        score_hints: Optional[Dict[str, Any]] = None
    ):
        raw_t = m.raw_staves.get(st.staff_id)
        elems = raw_t.elements if raw_t else []

        # Determine if this vocal line is Male or Female (Zero Second-Guessing of User Hints!)
        voicing_hint = (score_hints.get("choral_voicing") or "").lower() if score_hints else ""
        custom_hint = (score_hints.get("custom_instructions") or "").lower() if score_hints else ""
        label_hint = (st.label or "").lower()

        is_explicitly_male = any(
            k in voicing_hint or k in custom_hint or k in label_hint
            for k in ("male", "men", "tenor", "baritone", "bass", "tb", "ttbb")
        )
        is_explicitly_female = any(
            k in voicing_hint or k in custom_hint or k in label_hint
            for k in ("female", "women", "soprano", "alto", "sa", "ssaa")
        )

        if is_explicitly_male:
            is_male = True
        elif is_explicitly_female:
            is_male = False
        else:
            is_male = st.clef in ("bass", "treble_8vb")

        up_elems, low_elems = cls._split_divisi_elements(elems, m.quarter_length)

        if is_male:
            # Men's vocal line -> Tenor, Baritone, Bass active; Women rest!
            for p in ["soprano_1", "soprano_2", "alto_1", "alto_2"]:
                tracks[p].elements = [NoteElement(pitch=None, duration_quarters=m.quarter_length, duration_type="whole", is_rest=True)]
            for p in ["tenor_1", "tenor_2"]:
                tracks[p].elements = copy.deepcopy(up_elems)
            for p in ["baritone_1", "baritone_2", "bass_1", "bass_2"]:
                tracks[p].elements = copy.deepcopy(low_elems)
        else:
            # Women's vocal line -> Soprano, Alto active; Men rest!
            for p in ["soprano_1", "soprano_2"]:
                tracks[p].elements = copy.deepcopy(up_elems)
            for p in ["alto_1", "alto_2"]:
                tracks[p].elements = copy.deepcopy(low_elems)
            for p in ["tenor_1", "tenor_2", "baritone_1", "baritone_2", "bass_1", "bass_2"]:
                tracks[p].elements = [NoteElement(pitch=None, duration_quarters=m.quarter_length, duration_type="whole", is_rest=True)]

    @classmethod
    def _route_two_vocal_staves(cls, st_upper: StaffInfo, st_lower: StaffInfo, m: MeasureData, tracks: Dict[str, TrackData]):
        raw_top = m.raw_staves.get(st_upper.staff_id)
        raw_bot = m.raw_staves.get(st_lower.staff_id)

        top_elems = raw_top.elements if raw_top else []
        bot_elems = raw_bot.elements if raw_bot else []

        top_up, top_low = cls._split_divisi_elements(top_elems, m.quarter_length)
        bot_up, bot_low = cls._split_divisi_elements(bot_elems, m.quarter_length)

        is_both_treble = (st_upper.clef == "treble" and st_lower.clef == "treble")
        is_both_bass = (st_upper.clef in ("bass", "treble_8vb") and st_lower.clef in ("bass", "treble_8vb"))

        if is_both_treble:
            # Both staves are Treble -> All female / women parts (SSAA / SA)
            tracks["soprano_1"].elements = copy.deepcopy(top_up)
            tracks["soprano_2"].elements = copy.deepcopy(top_low)
            tracks["alto_1"].elements = copy.deepcopy(bot_up)
            tracks["alto_2"].elements = copy.deepcopy(bot_low)
            for p in ["tenor_1", "tenor_2", "baritone_1", "baritone_2", "bass_1", "bass_2"]:
                tracks[p].elements = [NoteElement(pitch=None, duration_quarters=m.quarter_length, duration_type="whole", is_rest=True)]
        elif is_both_bass:
            # Both staves are Bass/Treble_8vb -> All male / men parts (TTBB / TB)
            for p in ["soprano_1", "soprano_2", "alto_1", "alto_2"]:
                tracks[p].elements = [NoteElement(pitch=None, duration_quarters=m.quarter_length, duration_type="whole", is_rest=True)]
            tracks["tenor_1"].elements = copy.deepcopy(top_up)
            tracks["tenor_2"].elements = copy.deepcopy(top_low)
            tracks["baritone_1"].elements = copy.deepcopy(bot_up)
            tracks["baritone_2"].elements = copy.deepcopy(bot_up)
            tracks["bass_1"].elements = copy.deepcopy(bot_low)
            tracks["bass_2"].elements = copy.deepcopy(bot_low)
        else:
            # Treble staff on top (Women: Soprano/Alto), Bass staff on bottom (Men: Tenor/Bass)
            tracks["soprano_1"].elements = copy.deepcopy(top_up)
            tracks["soprano_2"].elements = copy.deepcopy(top_up)
            tracks["alto_1"].elements = copy.deepcopy(top_low)
            tracks["alto_2"].elements = copy.deepcopy(top_low)

            tracks["tenor_1"].elements = copy.deepcopy(bot_up)
            tracks["tenor_2"].elements = copy.deepcopy(bot_up)
            tracks["baritone_1"].elements = copy.deepcopy(bot_low)
            tracks["baritone_2"].elements = copy.deepcopy(bot_low)
            tracks["bass_1"].elements = copy.deepcopy(bot_low)
            tracks["bass_2"].elements = copy.deepcopy(bot_low)

    @classmethod
    def _route_four_vocal_staves(cls, staves: List[StaffInfo], m: MeasureData, tracks: Dict[str, TrackData]):
        # Match by explicit part label first if available
        s_staff = next((st for st in staves if st.label and any(k in st.label.lower() for k in ("soprano", "s.", "s1"))), None)
        a_staff = next((st for st in staves if st.label and any(k in st.label.lower() for k in ("alto", "a.", "a1"))), None)
        t_staff = next((st for st in staves if st.label and any(k in st.label.lower() for k in ("tenor", "t.", "t1"))), None)
        b_staff = next((st for st in staves if st.label and any(k in st.label.lower() for k in ("bass", "b.", "b1", "baritone"))), None)

        if not (s_staff and a_staff and t_staff and b_staff):
            sorted_staves = sorted(staves, key=lambda s: s.y_top)
            s_staff = sorted_staves[0]
            a_staff = sorted_staves[1]
            t_staff = sorted_staves[2]
            b_staff = sorted_staves[3]

        s_raw = m.raw_staves.get(s_staff.staff_id)
        a_raw = m.raw_staves.get(a_staff.staff_id)
        t_raw = m.raw_staves.get(t_staff.staff_id)
        b_raw = m.raw_staves.get(b_staff.staff_id)

        s_up, s_low = cls._split_divisi_elements(s_raw.elements if s_raw else [], m.quarter_length)
        a_up, a_low = cls._split_divisi_elements(a_raw.elements if a_raw else [], m.quarter_length)
        t_up, t_low = cls._split_divisi_elements(t_raw.elements if t_raw else [], m.quarter_length)
        b_up, b_low = cls._split_divisi_elements(b_raw.elements if b_raw else [], m.quarter_length)

        tracks["soprano_1"].elements = s_up
        tracks["soprano_2"].elements = s_low
        tracks["alto_1"].elements = a_up
        tracks["alto_2"].elements = a_low
        tracks["tenor_1"].elements = t_up
        tracks["tenor_2"].elements = t_low
        tracks["baritone_1"].elements = b_up
        tracks["baritone_2"].elements = b_up
        tracks["bass_1"].elements = b_low
        tracks["bass_2"].elements = b_low

    @classmethod
    def _route_three_vocal_staves(cls, staves: List[StaffInfo], m: MeasureData, tracks: Dict[str, TrackData]):
        # S, A, TB or SA, T, B
        r0 = m.raw_staves.get(staves[0].staff_id)
        r1 = m.raw_staves.get(staves[1].staff_id)
        r2 = m.raw_staves.get(staves[2].staff_id)

        e0 = r0.elements if r0 else []
        e1 = r1.elements if r1 else []
        e2 = r2.elements if r2 else []

        if staves[1].clef != "bass":
            # Soprano, Alto, Men (TB)
            tracks["soprano_1"].elements = copy.deepcopy(e0)
            tracks["soprano_2"].elements = copy.deepcopy(e0)
            tracks["alto_1"].elements = copy.deepcopy(e1)
            tracks["alto_2"].elements = copy.deepcopy(e1)

            t_elems, b_elems = cls._split_divisi_elements(e2, m.quarter_length)
            tracks["tenor_1"].elements = copy.deepcopy(t_elems)
            tracks["tenor_2"].elements = copy.deepcopy(t_elems)
            tracks["baritone_1"].elements = copy.deepcopy(b_elems)
            tracks["baritone_2"].elements = copy.deepcopy(b_elems)
            tracks["bass_1"].elements = copy.deepcopy(b_elems)
            tracks["bass_2"].elements = copy.deepcopy(b_elems)
        else:
            # Women (SA), Tenor, Bass
            s_elems, a_elems = cls._split_divisi_elements(e0, m.quarter_length)
            tracks["soprano_1"].elements = copy.deepcopy(s_elems)
            tracks["soprano_2"].elements = copy.deepcopy(s_elems)
            tracks["alto_1"].elements = copy.deepcopy(a_elems)
            tracks["alto_2"].elements = copy.deepcopy(a_elems)

            tracks["tenor_1"].elements = copy.deepcopy(e1)
            tracks["tenor_2"].elements = copy.deepcopy(e1)
            tracks["baritone_1"].elements = copy.deepcopy(e2)
            tracks["baritone_2"].elements = copy.deepcopy(e2)
            tracks["bass_1"].elements = copy.deepcopy(e2)
            tracks["bass_2"].elements = copy.deepcopy(e2)

    @classmethod
    def _split_divisi_elements(cls, elements: List[NoteElement], bar_ql: float) -> Tuple[List[NoteElement], List[NoteElement]]:
        if not elements:
            r = [NoteElement(pitch=None, duration_quarters=bar_ql, duration_type="whole", is_rest=True)]
            return r, copy.deepcopy(r)

        # Check if measure exhibits two distinct polyphonic stem streams
        has_up_stems = any(el.stem_direction == "up" and not el.is_rest for el in elements)
        has_down_stems = any(el.stem_direction == "down" and not el.is_rest for el in elements)
        polyphonic_stem_voices = has_up_stems and has_down_stems

        up_list: List[NoteElement] = []
        low_list: List[NoteElement] = []

        if polyphonic_stem_voices:
            # Polyphonic 2-voice splitting by stem direction
            for el in elements:
                if el.is_rest:
                    up_list.append(el.model_copy())
                    low_list.append(el.model_copy())
                elif el.stem_direction == "up":
                    up_list.append(el.model_copy())
                elif el.stem_direction == "down":
                    low_list.append(el.model_copy())
                else:
                    # Unstemmed or shared notehead (unison or shared rhythm)
                    up_list.append(el.model_copy())
                    low_list.append(el.model_copy())

            # Balance offsets and rests with MusicTheoryEngine
            up_list = MusicTheoryEngine.solve_measure_rhythm(up_list, bar_quarter_length=bar_ql)
            low_list = MusicTheoryEngine.solve_measure_rhythm(low_list, bar_quarter_length=bar_ql)
            return up_list, low_list

        for el in elements:
            if el.is_chord and len(el.chord_pitches) >= 2:
                # Top pitch to upper voice, bottom pitch to lower voice based on true MIDI pitch
                sorted_p = sorted(
                    el.chord_pitches,
                    key=lambda p: MusicTheoryEngine.pitch_to_midi(p) if isinstance(p, str) else 60
                )
                el_up = el.model_copy()
                el_up.pitch = sorted_p[-1]
                el_up.midi_pitch = MusicTheoryEngine.pitch_to_midi(sorted_p[-1])
                el_up.is_chord = False
                el_up.chord_pitches = []

                el_low = el.model_copy()
                el_low.pitch = sorted_p[0]
                el_low.midi_pitch = MusicTheoryEngine.pitch_to_midi(sorted_p[0])
                el_low.is_chord = False
                el_low.chord_pitches = []

                up_list.append(el_up)
                low_list.append(el_low)
            else:
                up_list.append(el.model_copy())
                low_list.append(el.model_copy())

        return up_list, low_list
