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


def run_score_pipeline(score_id: str):
    """
    Main background pipeline execution for a score:
    1. OMR (if PDF): Audiveris -> MusicXML
    2. Notation processing: voice splitting, SATB normalization, stem MIDI export
    3. Audio synthesis: FluidSynth / fallback synthesis -> WAV/MP3 stems
    4. Database update to 'ready' (or 'failed' on error)
    """
    db: Session = database.SessionLocal()
    try:
        score = db.query(Score).filter(Score.id == score_id).first()
        if not score:
            logger.error("Score not found for pipeline execution: %s", score_id)
            return

        logger.info("Starting processing pipeline for score: %s (%s)", score.id, score.filename)
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
            db.commit()

            try:
                xml_file_path = omr_engine.process_pdf(original_file, score_xml_dir)
            except Exception as e:
                logger.error("OMR processing failed for score %s: %s", score.id, e)
                score.status = "failed"
                score.error_message = f"OMR processing failed: {str(e)}"
                db.commit()
                return

        elif file_suffix in [".xml", ".musicxml", ".mxl"]:
            logger.info("Score is direct MusicXML/MXL, skipping OMR.")
            # Copy to score xml directory
            dest_xml = score_xml_dir / original_file.name
            shutil.copy2(original_file, dest_xml)
            xml_file_path = dest_xml
        elif file_suffix in [".mid", ".midi"]:
            logger.info("Score is MIDI, skipping OMR.")
            dest_mid = score_midi_dir / original_file.name
            shutil.copy2(original_file, dest_mid)
            xml_file_path = dest_mid
        else:
            score.status = "failed"
            score.error_message = f"Unsupported file extension: {file_suffix}"
            db.commit()
            return

        score.xml_path = str(xml_file_path)
        db.commit()

        # ----------------------------------------------------
        # STEP 2: Symbolic Notation Processing & Voice Splitting
        # ----------------------------------------------------
        logger.info("Parsing notation and splitting choral parts...")
        score.status = "parsing"
        db.commit()

        try:
            m21_score = notation_processor.parse_score(xml_file_path)
            title, composer = notation_processor.extract_metadata(m21_score, fallback_title=score.title)
            score.title = title
            if composer:
                score.composer = composer

            extracted_stems = notation_processor.process_and_extract_stems(
                m21_score,
                output_xml_dir=score_xml_dir,
                output_midi_dir=score_midi_dir,
            )

            if not extracted_stems:
                raise ValueError("No choral or accompaniment parts could be extracted from score.")

            score.detected_parts = [s.part_name for s in extracted_stems]
            db.commit()
        except Exception as e:
            logger.error("Notation parsing failed for score %s: %s\n%s", score.id, e, traceback.format_exc())
            score.status = "failed"
            score.error_message = f"Notation parsing failed: {str(e)}"
            db.commit()
            return

        # ----------------------------------------------------
        # STEP 3: Audio Synthesis for Stems
        # ----------------------------------------------------
        logger.info("Synthesizing isolated audio stems...")
        score.status = "synthesizing"
        db.commit()

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

            db.commit()

            # ----------------------------------------------------
            # STEP 4: Ready
            # ----------------------------------------------------
            score.status = "ready"
            score.error_message = None
            db.commit()
            logger.info("Score %s processing successfully completed! Status: READY", score.id)

        except Exception as e:
            logger.error("Synthesis failed for score %s: %s\n%s", score.id, e, traceback.format_exc())
            score.status = "failed"
            score.error_message = f"Synthesis failed: {str(e)}"
            db.commit()

    except Exception as exc:
        logger.error("Unhandled pipeline exception for score %s: %s", score_id, exc)
    finally:
        db.close()
