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

logger = logging.getLogger("voice_router_svc")


class VoiceRouterEngine:
    """
    Ingests Raw CISM JSON and normalizes staves into the 11 canonical rehearsal parts:
    soprano_1, soprano_2, alto_1, alto_2, tenor_1, tenor_2, baritone_1, baritone_2, bass_1, bass_2, piano.
    Applies unison duplication, divisi splitting, accompaniment anchoring, and interlude suppression.
    """

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

            for st in sys.staves:
                if st.bracket_type == "brace" or st.role in ("piano_rh", "piano_lh"):
                    piano_staves.append(st)
                else:
                    vocal_staves.append(st)

            # Fallback bottom-up anchor if 3+ staves and none explicitly marked brace
            if not piano_staves and len(sys.staves) >= 3 and cism_out.has_piano:
                piano_staves = sys.staves[-2:]
                vocal_staves = sys.staves[:-2]
            elif not piano_staves and len(sys.staves) == 2 and cism_out.has_piano:
                has_vocal_label = any(
                    st.label and any(k in st.label.lower() for k in ("soprano", "alto", "tenor", "bass", "men", "women"))
                    for st in sys.staves
                )
                if not has_vocal_label:
                    piano_staves = sys.staves
                    vocal_staves = []

            for m in sys.measures:
                m.tracks = cls._route_measure(
                    m=m,
                    vocal_staves=vocal_staves,
                    piano_staves=piano_staves,
                    has_piano_in_score=cism_out.has_piano,
                    overrides=overrides
                )

        return cism_out

    @classmethod
    def _route_measure(
        cls,
        m: MeasureData,
        vocal_staves: List[StaffInfo],
        piano_staves: List[StaffInfo],
        has_piano_in_score: bool,
        overrides: Optional[Dict[str, Any]]
    ) -> Dict[str, TrackData]:
        tracks: Dict[str, TrackData] = {}
        for p in CANONICAL_11_PARTS:
            tracks[p] = TrackData(
                track_name=p,
                clef=PART_METADATA[p]["default_clef"],
                elements=[]
            )

        # 1. Route Piano Accompaniment (Rule A1a & Rule A5)
        piano_elements: List[NoteElement] = []
        if piano_staves and has_piano_in_score:
            for pst in piano_staves:
                raw_t = m.raw_staves.get(pst.staff_id)
                if raw_t:
                    piano_elements.extend(copy.deepcopy(raw_t.elements))
        
        if not piano_elements:
            tracks["piano"].elements = [
                NoteElement(pitch=None, duration_quarters=m.quarter_length, duration_type="whole", offset_quarters=0.0, is_rest=True)
            ]
        else:
            tracks["piano"].elements = piano_elements

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
            cls._route_single_vocal_staff(vocal_staves[0], m, tracks)
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
    def _route_single_vocal_staff(cls, st: StaffInfo, m: MeasureData, tracks: Dict[str, TrackData]):
        raw_t = m.raw_staves.get(st.staff_id)
        elems = raw_t.elements if raw_t else []
        is_bass = st.clef == "bass"

        up_elems, low_elems = cls._split_divisi_elements(elems, m.quarter_length)

        if is_bass:
            # Men's unison/divisi -> Tenor, Baritone, Bass active; Women rest
            for p in ["soprano_1", "soprano_2", "alto_1", "alto_2"]:
                tracks[p].elements = [NoteElement(pitch=None, duration_quarters=m.quarter_length, duration_type="whole", is_rest=True)]
            for p in ["tenor_1", "tenor_2"]:
                tracks[p].elements = copy.deepcopy(up_elems)
            for p in ["baritone_1", "baritone_2", "bass_1", "bass_2"]:
                tracks[p].elements = copy.deepcopy(low_elems)
        else:
            # Women's unison/divisi -> Soprano, Alto active; Men rest
            for p in ["soprano_1", "soprano_2"]:
                tracks[p].elements = copy.deepcopy(up_elems)
            for p in ["alto_1", "alto_2"]:
                tracks[p].elements = copy.deepcopy(low_elems)
            for p in ["tenor_1", "tenor_2", "baritone_1", "baritone_2", "bass_1", "bass_2"]:
                tracks[p].elements = [NoteElement(pitch=None, duration_quarters=m.quarter_length, duration_type="whole", is_rest=True)]

    @classmethod
    def _route_two_vocal_staves(cls, st_upper: StaffInfo, st_lower: StaffInfo, m: MeasureData, tracks: Dict[str, TrackData]):
        raw_sa = m.raw_staves.get(st_upper.staff_id)
        raw_tb = m.raw_staves.get(st_lower.staff_id)

        sa_elems = raw_sa.elements if raw_sa else []
        tb_elems = raw_tb.elements if raw_tb else []

        s_elems, a_elems = cls._split_divisi_elements(sa_elems, m.quarter_length)
        t_elems, b_elems = cls._split_divisi_elements(tb_elems, m.quarter_length)

        tracks["soprano_1"].elements = copy.deepcopy(s_elems)
        tracks["soprano_2"].elements = copy.deepcopy(s_elems)
        tracks["alto_1"].elements = copy.deepcopy(a_elems)
        tracks["alto_2"].elements = copy.deepcopy(a_elems)

        tracks["tenor_1"].elements = copy.deepcopy(t_elems)
        tracks["tenor_2"].elements = copy.deepcopy(t_elems)
        tracks["baritone_1"].elements = copy.deepcopy(b_elems)
        tracks["baritone_2"].elements = copy.deepcopy(b_elems)
        tracks["bass_1"].elements = copy.deepcopy(b_elems)
        tracks["bass_2"].elements = copy.deepcopy(b_elems)

    @classmethod
    def _route_four_vocal_staves(cls, staves: List[StaffInfo], m: MeasureData, tracks: Dict[str, TrackData]):
        s_raw = m.raw_staves.get(staves[0].staff_id)
        a_raw = m.raw_staves.get(staves[1].staff_id)
        t_raw = m.raw_staves.get(staves[2].staff_id)
        b_raw = m.raw_staves.get(staves[3].staff_id)

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

        up_list: List[NoteElement] = []
        low_list: List[NoteElement] = []

        for el in elements:
            if el.is_chord and len(el.chord_pitches) >= 2:
                # Top pitch to upper, bottom pitch to lower
                sorted_p = sorted(el.chord_pitches)
                el_up = el.model_copy()
                el_up.pitch = sorted_p[-1]
                el_up.is_chord = False
                el_up.chord_pitches = []

                el_low = el.model_copy()
                el_low.pitch = sorted_p[0]
                el_low.is_chord = False
                el_low.chord_pitches = []

                up_list.append(el_up)
                low_list.append(el_low)
            elif el.stem_direction == "up":
                up_list.append(el.model_copy())
                # Lower part rests or doubles
                low_list.append(el.model_copy())
            elif el.stem_direction == "down":
                low_list.append(el.model_copy())
                up_list.append(el.model_copy())
            else:
                up_list.append(el.model_copy())
                low_list.append(el.model_copy())

        return up_list, low_list
