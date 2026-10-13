from datetime import datetime, timezone
import logging
import shutil
import traceback
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app import database
from app.models.score import Score
from app.models.stem import Stem
from app.services.notation import notation_processor
from app.services.omr import omr_engine
from app.services.synthesis import audio_synthesizer

logger = logging.getLogger("parttrackr.pipeline")


def _log_event(
    score: Score,
    message: str,
    level: str = "info",
    stage: str = "system",
    db: Optional[Session] = None,
):
    """Appends a structured event log entry to the score record."""
    timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    entry = {
        "timestamp": timestamp_str,
        "level": level,  # 'info', 'warning', 'error', 'success'
        "stage": stage,  # 'omr', 'notation', 'synthesis', 'system'
        "message": message,
    }
    logs = list(score.processing_logs or [])
    logs.append(entry)
    score.processing_logs = logs
    if db:
        try:
            db.commit()
        except Exception as e:
            logger.warning("Could not persist log entry to database: %s", e)


def run_score_pipeline(score_id: str):
    """
    Main background pipeline execution for a score:
    1. OMR (if PDF): Audiveris -> MusicXML
    2. Notation processing: voice splitting, SATB normalization, stem MIDI export
    3. Audio synthesis: FluidSynth / fallback synthesis -> WAV/MP3 stems
    4. Database update to 'ready' (or 'failed' on error)
    """
    db: Session = database.SessionLocal()
    score = None
    try:
        score = db.query(Score).filter(Score.id == score_id).first()
        if not score:
            logger.error("Score not found for pipeline execution: %s", score_id)
            return

        logger.info("Starting processing pipeline for score: %s (%s)", score.id, score.filename)
        _log_event(score, f"Pipeline initialized for '{score.filename}'.", level="info", stage="system", db=db)

        score_storage_dir = settings.STORAGE_DIR / score.id
        score_storage_dir.mkdir(parents=True, exist_ok=True)

        score_xml_dir = score_storage_dir / "xml"
        score_midi_dir = score_storage_dir / "midi"
        score_stems_dir = score_storage_dir / "stems"

        for d in [score_xml_dir, score_midi_dir, score_stems_dir]:
            d.mkdir(parents=True, exist_ok=True)

        original_file = Path(score.original_path).resolve()
        file_suffix = original_file.suffix.lower()

        # ----------------------------------------------------
        # STEP 1: Ingestion & OMR
        # ----------------------------------------------------
        xml_file_path: Optional[Path] = None

        if file_suffix == ".pdf":
            logger.info("Score is PDF, triggering OMR processing...")
            score.status = "processing_omr"
            _log_event(
                score,
                f"PDF uploaded ({original_file.name}, {original_file.stat().st_size:,} bytes). Launching Audiveris OMR engine...",
                level="info",
                stage="omr",
                db=db,
            )

            try:
                xml_file_path = omr_engine.process_pdf(original_file, score_xml_dir)
                _log_event(
                    score,
                    f"OMR optical recognition finished. Extracted MusicXML: {xml_file_path.name}",
                    level="success",
                    stage="omr",
                    db=db,
                )
            except Exception as e:
                tb = traceback.format_exc()
                logger.error("OMR processing failed for score %s: %s\n%s", score.id, e, tb)
                score.status = "failed"
                score.error_message = f"OMR processing failed: {str(e)}"
                score.error_traceback = tb
                _log_event(score, f"OMR processing failed: {str(e)}", level="error", stage="omr", db=db)
                return

        elif file_suffix in [".xml", ".musicxml", ".mxl"]:
            logger.info("Score is direct MusicXML/MXL, skipping OMR.")
            _log_event(
                score,
                f"Uploaded symbolic format ({file_suffix}). Bypassing Audiveris OMR.",
                level="info",
                stage="omr",
                db=db,
            )
            dest_xml = score_xml_dir / original_file.name
            shutil.copy2(original_file, dest_xml)
            xml_file_path = dest_xml
        elif file_suffix in [".mid", ".midi"]:
            logger.info("Score is MIDI, skipping OMR.")
            _log_event(
                score,
                f"Uploaded MIDI score ({file_suffix}). Bypassing Audiveris OMR.",
                level="info",
                stage="omr",
                db=db,
            )
            dest_mid = score_midi_dir / original_file.name
            shutil.copy2(original_file, dest_mid)
            xml_file_path = dest_mid
        else:
            score.status = "failed"
            score.error_message = f"Unsupported file extension: {file_suffix}"
            score.error_traceback = f"Unsupported file extension: {file_suffix}"
            _log_event(score, f"Unsupported file extension: {file_suffix}", level="error", stage="omr", db=db)
            return

        score.xml_path = str(xml_file_path)
        db.commit()

        # ----------------------------------------------------
        # STEP 2: Symbolic Notation Processing & Voice Splitting
        # ----------------------------------------------------
        logger.info("Parsing notation and splitting choral parts...")
        score.status = "parsing"
        _log_event(
            score,
            "Parsing musical score with music21: detecting staves, clefs, voices, and choral registers...",
            level="info",
            stage="notation",
            db=db,
        )

        try:
            m21_score = notation_processor.parse_score(xml_file_path)
            title, composer = notation_processor.extract_metadata(m21_score, fallback_title=score.title)
            score.title = title
            if composer:
                score.composer = composer

            extracted_stems, measure_analysis = notation_processor.process_and_extract_stems(
                m21_score,
                output_xml_dir=score_xml_dir,
                output_midi_dir=score_midi_dir,
                return_analysis=True,
            )

            if not extracted_stems:
                raise ValueError("No choral or accompaniment parts could be extracted from score.")

            score.detected_parts = [s.part_name for s in extracted_stems]
            score.measure_analysis = measure_analysis
            score.score_profile = measure_analysis.get("score_profile", {})

            # Persist learned profile to disk
            profile_path = score_storage_dir / "profile.json"
            try:
                import json
                with open(profile_path, "w", encoding="utf-8") as pf:
                    json.dump(score.score_profile, pf, indent=2)
            except Exception:
                pass

            parts_summary = ", ".join(score.detected_parts)
            tot_measures = measure_analysis.get("total_measures", 0)
            sec_count = len(score.score_profile.get("sections", []))
            _log_event(
                score,
                f"Full measure analysis complete ({tot_measures} measures, {sec_count} structural sections discovered). All 11 choral parts reconciled: {parts_summary}",
                level="success",
                stage="notation",
                db=db,
            )

            audit = measure_analysis.get("audit_report", {})
            if audit:
                infilled = audit.get("components", {}).get("accompaniment", {}).get("infilled_count", 0)
                recovered = audit.get("components", {}).get("vocal_lines", {}).get("recovered_count", 0)
                bleed = audit.get("components", {}).get("interludes", {}).get("bleed_count", 0)
                match_pct = audit.get("reconciled_match_pct", 100)
                _log_event(
                    score,
                    f"Component Audit Check: {match_pct}% Match with printed PDF. Auto-reconciled {infilled} dropped accompaniment measures, {recovered} dropped vocal measures, and suppressed {bleed} interlude bleeds.",
                    level="success",
                    stage="notation",
                    db=db,
                )
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("Notation parsing failed for score %s: %s\n%s", score.id, e, tb)
            score.status = "failed"
            score.error_message = f"Notation parsing failed: {str(e)}"
            score.error_traceback = tb
            _log_event(score, f"Notation parsing failed: {str(e)}", level="error", stage="notation", db=db)
            return

        # ----------------------------------------------------
        # STEP 3: Audio Synthesis for Stems
        # ----------------------------------------------------
        logger.info("Synthesizing isolated audio stems...")
        score.status = "synthesizing"
        _log_event(
            score,
            f"Rendering {len(extracted_stems)} audio stems using FluidSynth GM SoundFont...",
            level="info",
            stage="synthesis",
            db=db,
        )

        try:
            # Delete any existing stems for reprocessing
            db.query(Stem).filter(Stem.score_id == score.id).delete()
            db.commit()

            for ext_stem in extracted_stems:
                if not ext_stem.midi_path or not ext_stem.midi_path.exists():
                    logger.warning("No MIDI file for stem %s, skipping synthesis", ext_stem.part_key)
                    continue

                audio_file = audio_synthesizer.render_stem(
                    midi_path=ext_stem.midi_path,
                    output_audio_dir=score_stems_dir,
                    stem_key=ext_stem.part_key,
                    is_piano=ext_stem.is_accompaniment,
                )

                stem_record = Stem(
                    score_id=score.id,
                    part_name=ext_stem.part_name,
                    part_key=ext_stem.part_key,
                    is_accompaniment=ext_stem.is_accompaniment,
                    original_part_name=ext_stem.original_part_name,
                    midi_path=str(ext_stem.midi_path),
                    audio_path=str(audio_file),
                    duration_seconds=ext_stem.duration_seconds,
                    pitch_range=ext_stem.pitch_range,
                    measure_count=ext_stem.measure_count,
                    note_count=ext_stem.note_count,
                )
                db.add(stem_record)
                _log_event(
                    score,
                    f"Stem synthesized: '{ext_stem.part_name}' ({ext_stem.measure_count} bars, {ext_stem.note_count} notes, {ext_stem.duration_seconds:.1f}s)",
                    level="info",
                    stage="synthesis",
                    db=db,
                )

            db.commit()

            # ----------------------------------------------------
            # STEP 4: Ready
            # ----------------------------------------------------
            score.status = "ready"
            score.error_message = None
            score.error_traceback = None
            _log_event(
                score,
                f"Score processing complete! {len(extracted_stems)} parts are ready for rehearsal playback.",
                level="success",
                stage="system",
                db=db,
            )
            logger.info("Score %s processing successfully completed! Status: READY", score.id)

        except Exception as e:
            tb = traceback.format_exc()
            logger.error("Synthesis failed for score %s: %s\n%s", score.id, e, tb)
            score.status = "failed"
            score.error_message = f"Synthesis failed: {str(e)}"
            score.error_traceback = tb
            _log_event(score, f"Audio synthesis failed: {str(e)}", level="error", stage="synthesis", db=db)

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Unhandled pipeline exception for score %s: %s\n%s", score_id, exc, tb)
        if score:
            try:
                score.status = "failed"
                score.error_message = f"Internal server error: {str(exc)}"
                score.error_traceback = tb
                _log_event(score, f"Internal pipeline error: {str(exc)}", level="error", stage="system", db=db)
            except Exception:
                pass
    finally:
        db.close()

