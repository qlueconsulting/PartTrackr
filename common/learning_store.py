from __future__ import annotations
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from pydantic import BaseModel, Field

logger = logging.getLogger("learning_store")

DEFAULT_LEARNING_DIR = Path("storage/learning")


def get_learning_dir() -> Path:
    storage_root = os.environ.get("STORAGE_DIR")
    if storage_root:
        return Path(storage_root) / "learning"
    return DEFAULT_LEARNING_DIR


class ScoreStyleFingerprint(BaseModel):
    staves_per_system: int = 3
    inter_staff_gap_ratio: float = 1.0
    has_bracket: bool = False
    has_brace: bool = True
    composer_token: str = ""
    clef_pattern: List[str] = Field(default_factory=list)
    time_signature: Optional[str] = None
    is_scanned: bool = True


class StyleBlueprint(BaseModel):
    blueprint_id: str
    name: str
    composer_pattern: str = ".*"
    fingerprint: ScoreStyleFingerprint
    verified_config: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    confirmed_count: int = 1


class ExemplarItem(BaseModel):
    exemplar_id: str
    blueprint_id: str
    layout_type: str
    time_signature: str
    image_path: str
    cism_data: Dict[str, Any]
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class LearningManager:
    """
    Universal Multi-Composer Self-Learning Knowledge Core.
    Acts as the persistent memory of composer engraving styles, layout topologies,
    and user-verified ground-truth assignments (the Human-in-the-Loop teacher channel).
    """

    @classmethod
    def _ensure_dirs(cls) -> Tuple[Path, Path, Path]:
        learning_dir = get_learning_dir()
        exemplars_dir = learning_dir / "exemplars"
        dataset_dir = learning_dir / "dataset"
        learning_dir.mkdir(parents=True, exist_ok=True)
        exemplars_dir.mkdir(parents=True, exist_ok=True)
        dataset_dir.mkdir(parents=True, exist_ok=True)
        return learning_dir, exemplars_dir, dataset_dir

    @classmethod
    def _blueprints_path(cls) -> Path:
        learning_dir, _, _ = cls._ensure_dirs()
        return learning_dir / "style_blueprints.json"

    @classmethod
    def load_all_blueprints(cls) -> Dict[str, StyleBlueprint]:
        bp_path = cls._blueprints_path()
        if not bp_path.exists():
            # Seed with standard common blueprints
            seed = cls._get_default_seed_blueprints()
            cls.save_all_blueprints(seed)
            return seed

        try:
            with open(bp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {k: StyleBlueprint(**v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"Could not load style_blueprints.json: {e}, using defaults")
            return cls._get_default_seed_blueprints()

    @classmethod
    def save_all_blueprints(cls, blueprints: Dict[str, StyleBlueprint]):
        bp_path = cls._blueprints_path()
        try:
            dump_dict = {k: v.model_dump() for k, v in blueprints.items()}
            with open(bp_path, "w", encoding="utf-8") as f:
                json.dump(dump_dict, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save style_blueprints.json: {e}")

    @classmethod
    def match_style(
        cls,
        fingerprint: ScoreStyleFingerprint,
        composer: str = ""
    ) -> Tuple[Optional[StyleBlueprint], float]:
        """
        Calculates similarity between incoming score fingerprint and learned blueprints.
        Returns (best_blueprint, match_confidence_0_to_1).
        """
        blueprints = cls.load_all_blueprints()
        if not blueprints:
            return None, 0.0

        best_bp: Optional[StyleBlueprint] = None
        best_score = 0.0

        comp_clean = composer.strip().lower()

        for bp in blueprints.values():
            score = 0.0
            fp = bp.fingerprint

            # 1. Staves per system (Crucial structural anchor: 40 points)
            if fp.staves_per_system == fingerprint.staves_per_system:
                score += 0.40
            elif abs(fp.staves_per_system - fingerprint.staves_per_system) == 1:
                score += 0.10

            # 2. Composer Regex / Keyword Match (30 points)
            if bp.composer_pattern and comp_clean:
                try:
                    if re.search(bp.composer_pattern, comp_clean, re.IGNORECASE):
                        score += 0.30
                except Exception:
                    pass

            # 3. Piano Brace / Bracket Matching (15 points)
            if fp.has_brace == fingerprint.has_brace:
                score += 0.10
            if fp.has_bracket == fingerprint.has_bracket:
                score += 0.05

            # 4. Clef Profile Similarity (10 points)
            if fp.clef_pattern and fingerprint.clef_pattern:
                matches = sum(1 for a, b in zip(fp.clef_pattern, fingerprint.clef_pattern) if a == b)
                score += 0.10 * (matches / max(len(fp.clef_pattern), len(fingerprint.clef_pattern)))

            # 5. Time Signature Match (5 points)
            if fp.time_signature and fingerprint.time_signature and fp.time_signature == fingerprint.time_signature:
                score += 0.05

            if score > best_score:
                best_score = score
                best_bp = bp

        return best_bp, round(best_score, 2)

    @classmethod
    def record_teacher_signal(
        cls,
        job_id: str,
        title: str,
        composer: str,
        score_hints: Dict[str, Any],
        layout_data: Optional[Dict[str, Any]] = None,
        cism: Optional[Dict[str, Any]] = None
    ) -> StyleBlueprint:
        """
        Learns from user-provided AI Helps. Creates or updates the style blueprint
        and logs training data for continuous model adaptation.
        """
        cls._ensure_dirs()
        blueprints = cls.load_all_blueprints()

        comp_clean = composer.strip() or "Unknown Composer"
        staves_cnt = score_hints.get("staves_per_system") or (layout_data.get("staves_per_system") if layout_data else 3) or 3
        time_sig = score_hints.get("time_signature") or "4/4"
        choral_voicing = score_hints.get("choral_voicing") or "SATB"
        accompaniment_type = score_hints.get("accompaniment_type") or "piano"

        # Form a deterministic blueprint ID based on key layout tokens
        comp_slug = re.sub(r"[^\w]", "", comp_clean.lower())[:10] or "custom"
        bp_id = f"style_{comp_slug}_{staves_cnt}st_{time_sig.replace('/', '_')}"

        # Clean composer regex pattern
        words = [w for w in re.split(r"\W+", comp_clean) if len(w) >= 3 and w.lower() not in ("unknown", "composer", "traditional")]
        comp_pattern = ".*(" + "|".join(re.escape(w.lower()) for w in words) + ").*" if words else ".*"

        fingerprint = ScoreStyleFingerprint(
            staves_per_system=staves_cnt,
            inter_staff_gap_ratio=1.0,
            has_bracket=choral_voicing != "solo_male",
            has_brace=accompaniment_type in ("piano", "orchestra_reduction"),
            composer_token=comp_slug,
            time_signature=time_sig,
            is_scanned=True
        )

        verified_config = {
            "title_example": title,
            "composer": comp_clean,
            "staves_per_system": staves_cnt,
            "time_signature": time_sig,
            "tempo_bpm": score_hints.get("tempo_bpm", 120.0),
            "choral_voicing": choral_voicing,
            "accompaniment_type": accompaniment_type,
            "has_piano": accompaniment_type in ("piano", "orchestra_reduction"),
            "custom_instructions": score_hints.get("custom_instructions"),
            "part_layout_summary": score_hints.get("part_layout_summary") or f"{choral_voicing} with {accompaniment_type}",
        }

        if bp_id in blueprints:
            bp = blueprints[bp_id]
            bp.confirmed_count += 1
            bp.verified_config.update(verified_config)
            bp.fingerprint = fingerprint
        else:
            bp = StyleBlueprint(
                blueprint_id=bp_id,
                name=f"{comp_clean} ({staves_cnt}-Staff {choral_voicing} {time_sig})",
                composer_pattern=comp_pattern,
                fingerprint=fingerprint,
                verified_config=verified_config,
                confirmed_count=1
            )
            blueprints[bp_id] = bp

        cls.save_all_blueprints(blueprints)
        logger.info(f"Learned and saved Style Blueprint '{bp.name}' (ID: {bp_id})")

        # Also log to fine-tuning dataset JSONL
        cls._append_to_training_dataset(job_id, bp, score_hints, layout_data, cism)

        return bp

    @classmethod
    def _append_to_training_dataset(
        cls,
        job_id: str,
        bp: StyleBlueprint,
        score_hints: Dict[str, Any],
        layout_data: Optional[Dict[str, Any]],
        cism: Optional[Dict[str, Any]]
    ):
        """Appends verified interaction to storage/learning/dataset/choral_omr_dataset.jsonl"""
        try:
            _, _, dataset_dir = cls._ensure_dirs()
            dataset_file = dataset_dir / "choral_omr_dataset.jsonl"
            entry = {
                "job_id": job_id,
                "timestamp": datetime.utcnow().isoformat(),
                "blueprint_id": bp.blueprint_id,
                "composer": bp.verified_config.get("composer"),
                "staves_per_system": bp.fingerprint.staves_per_system,
                "time_signature": bp.fingerprint.time_signature,
                "choral_voicing": bp.verified_config.get("choral_voicing"),
                "custom_instructions": bp.verified_config.get("custom_instructions"),
                "total_measures": score_hints.get("total_measures"),
            }
            with open(dataset_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.debug(f"Could not append to training dataset: {e}")

    @classmethod
    def get_few_shot_prompt_text(
        cls,
        fingerprint: ScoreStyleFingerprint,
        composer: str = ""
    ) -> str:
        """
        Generates in-context few-shot demonstration text based on learned blueprints
        for injection into Multimodal LLM prompts.
        """
        matched_bp, confidence = cls.match_style(fingerprint, composer)
        if not matched_bp or confidence < 0.65:
            return ""

        cfg = matched_bp.verified_config
        lines = [
            f"--- LEARNED COMPOSER/EDITION STYLE TEMPLATE ({matched_bp.name}, {int(confidence * 100)}% match) ---",
            f"- Layout Topology: Exactly {cfg.get('staves_per_system', 3)} staves per system.",
        ]
        if cfg.get("staves_per_system") == 3:
            lines.append("- Staff 0 (Top Staff): Vocal melody line (assigned to Men/Tenor-Bass).")
            lines.append("- Staff 1 (Middle Staff): Piano Treble RH accompaniment.")
            lines.append("- Staff 2 (Bottom Staff): Piano Bass LH accompaniment.")
        if cfg.get("time_signature"):
            lines.append(f"- Verified Metric Ground Truth: Time signature is {cfg.get('time_signature')}.")
        if cfg.get("custom_instructions"):
            lines.append(f"- Directives: {cfg.get('custom_instructions')}")
        lines.append("---------------------------------------------------------------------------------")
        return "\n".join(lines)

    @classmethod
    def _get_default_seed_blueprints(cls) -> Dict[str, StyleBlueprint]:
        """Provides default foundational blueprints for common choral layouts."""
        b1 = StyleBlueprint(
            blueprint_id="choral_3staff_male_piano_68",
            name="Solo Male / Men's Chorus + Piano (3-Staff, 6/8)",
            composer_pattern=".*(stewart|caroling|male|men).*",
            fingerprint=ScoreStyleFingerprint(
                staves_per_system=3,
                inter_staff_gap_ratio=1.0,
                has_bracket=False,
                has_brace=True,
                time_signature="6/8",
                is_scanned=True
            ),
            verified_config={
                "staves_per_system": 3,
                "time_signature": "6/8",
                "choral_voicing": "Tenor_Bass",
                "accompaniment_type": "piano",
                "has_piano": True,
                "custom_instructions": "Top staff is male vocal line; bottom two staves are piano accompaniment (piano RH and piano LH).",
                "part_layout_summary": "Men's Chorus (1 vocal staff) + Piano Accompaniment (2 staves)"
            },
            confirmed_count=5
        )
        b2 = StyleBlueprint(
            blueprint_id="choral_4staff_satb_piano_44",
            name="SATB Choral + Piano Accompaniment (4-Staff, 4/4)",
            composer_pattern=".*(handel|bach|rutter|stainer|choral).*",
            fingerprint=ScoreStyleFingerprint(
                staves_per_system=4,
                inter_staff_gap_ratio=1.0,
                has_bracket=True,
                has_brace=True,
                time_signature="4/4",
                is_scanned=True
            ),
            verified_config={
                "staves_per_system": 4,
                "time_signature": "4/4",
                "choral_voicing": "SA_TB",
                "accompaniment_type": "piano",
                "has_piano": True,
                "custom_instructions": "Staves 1-2 are Soprano/Alto and Tenor/Bass; bottom 2 staves are piano accompaniment.",
                "part_layout_summary": "Choral SA/TB (2 staves) + Piano Accompaniment (2 staves)"
            },
            confirmed_count=5
        )
        return {b1.blueprint_id: b1, b2.blueprint_id: b2}
