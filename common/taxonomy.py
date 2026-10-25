from typing import Dict, Any, List

CANONICAL_11_PARTS = [
    "soprano_1",
    "soprano_2",
    "alto_1",
    "alto_2",
    "tenor_1",
    "tenor_2",
    "baritone_1",
    "baritone_2",
    "bass_1",
    "bass_2",
    "piano",
]

LEGACY_STEM_MAP = {
    "S1": "soprano_1",
    "S2": "soprano_2",
    "A1": "alto_1",
    "A2": "alto_2",
    "T1": "tenor_1",
    "T2": "tenor_2",
    "Bar1": "baritone_1",
    "Bar2": "baritone_2",
    "B1": "bass_1",
    "B2": "bass_2",
    "Piano": "piano",
}

CANONICAL_TO_LEGACY_MAP = {v: k for k, v in LEGACY_STEM_MAP.items()}

PART_METADATA: Dict[str, Dict[str, Any]] = {
    "soprano_1": {
        "display_name": "Soprano I",
        "category": "soprano",
        "default_pan": -0.6,
        "gm_program": 52,  # Choir Aahs
        "default_clef": "treble",
        "channel": 1,
    },
    "soprano_2": {
        "display_name": "Soprano II",
        "category": "soprano",
        "default_pan": -0.4,
        "gm_program": 52,
        "default_clef": "treble",
        "channel": 2,
    },
    "alto_1": {
        "display_name": "Alto I",
        "category": "alto",
        "default_pan": -0.2,
        "gm_program": 52,
        "default_clef": "treble",
        "channel": 3,
    },
    "alto_2": {
        "display_name": "Alto II",
        "category": "alto",
        "default_pan": 0.0,
        "gm_program": 52,
        "default_clef": "treble",
        "channel": 4,
    },
    "tenor_1": {
        "display_name": "Tenor I",
        "category": "tenor",
        "default_pan": 0.2,
        "gm_program": 53,  # Voice Oohs
        "default_clef": "treble_8vb",
        "channel": 5,
    },
    "tenor_2": {
        "display_name": "Tenor II",
        "category": "tenor",
        "default_pan": 0.4,
        "gm_program": 53,
        "default_clef": "treble_8vb",
        "channel": 6,
    },
    "baritone_1": {
        "display_name": "Baritone I",
        "category": "baritone",
        "default_pan": 0.5,
        "gm_program": 54,  # Synth Voice
        "default_clef": "bass",
        "channel": 7,
    },
    "baritone_2": {
        "display_name": "Baritone II",
        "category": "baritone",
        "default_pan": 0.6,
        "gm_program": 54,
        "default_clef": "bass",
        "channel": 8,
    },
    "bass_1": {
        "display_name": "Bass I",
        "category": "bass",
        "default_pan": 0.7,
        "gm_program": 54,
        "default_clef": "bass",
        "channel": 10,  # Melodic channel (GM Channel 9 is reserved for percussion/drums)
    },
    "bass_2": {
        "display_name": "Bass II",
        "category": "bass",
        "default_pan": 0.8,
        "gm_program": 54,
        "default_clef": "bass",
        "channel": 11,
    },
    "piano": {
        "display_name": "Piano Accompaniment",
        "category": "accompaniment",
        "default_pan": 0.0,
        "gm_program": 0,  # Acoustic Grand Piano
        "default_clef": "grand",
        "channel": 0,
    },
}
