import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger("parttrackr.omr")


class OMREngine:
    """Optical Music Recognition service using headless Audiveris CLI."""

    def __init__(self, audiveris_bin: Optional[str] = None):
        self.explicit_bin = audiveris_bin

    def get_bin(self) -> str:
        candidates = [
            self.explicit_bin,
            settings.AUDIVERIS_BIN,
            "audiveris",
            "Audiveris",
            "/opt/audiveris/bin/Audiveris",
            "/opt/audiveris/bin/audiveris",
            "/usr/local/bin/audiveris",
            "/usr/bin/audiveris",
        ]
        for c in candidates:
            if c and shutil.which(c):
                return c
        return self.explicit_bin or settings.AUDIVERIS_BIN

    def is_available(self) -> bool:
        """Check if Audiveris CLI is accessible in PATH or configured location."""
        return shutil.which(self.get_bin()) is not None

    def process_pdf(self, pdf_path: Path, output_dir: Path) -> Path:
        """
        Process a PDF sheet music score using Audiveris in headless batch mode.
        Command format:
            audiveris -batch -export -output <output_dir> <pdf_path>
        Returns the Path to the generated MusicXML / MXL file.
        """
        pdf_path = Path(pdf_path).resolve()
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

        bin_path = self.get_bin()
        if not self.is_available():
            raise RuntimeError(
                f"Audiveris CLI binary '{bin_path}' not found on system PATH. "
                "Audiveris is required for PDF Optical Music Recognition. "
                "In local dev without Audiveris, you can upload MusicXML (.musicxml / .mxl / .xml) directly."
            )

        cmd = [
            bin_path,
            "-batch",
            "-export",
            "-output",
            str(output_dir),
            str(pdf_path),
        ]

        logger.info("Executing Audiveris OMR: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout for multi-page scores
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"Audiveris OMR processing timed out after 600s: {exc}")
        except Exception as exc:
            raise RuntimeError(f"Failed to execute Audiveris: {exc}")

        if result.returncode != 0:
            logger.error(
                "Audiveris process failed with code %d. Stderr: %s. Stdout: %s",
                result.returncode,
                result.stderr,
                result.stdout,
            )
            raise RuntimeError(
                f"Audiveris OMR failed (exit code {result.returncode}):\n{result.stderr or result.stdout}"
            )

        # Locate the exported MusicXML / MXL file
        # Audiveris usually outputs files as <stem>/<stem>.mxl or <stem>.mxl
        stem_name = pdf_path.stem
        candidates = list(output_dir.glob(f"**/{stem_name}*.mxl")) + \
                     list(output_dir.glob(f"**/{stem_name}*.xml")) + \
                     list(output_dir.glob("**/*.mxl")) + \
                     list(output_dir.glob("**/*.xml"))

        if not candidates:
            raise FileNotFoundError(
                f"Audiveris completed but no MusicXML (.mxl / .xml) output was found in {output_dir}. "
                f"Stdout: {result.stdout}"
            )

        # Return the newest generated file
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        xml_file = candidates[0]
        logger.info("Audiveris OMR succeeded, produced: %s", xml_file)
        return xml_file


omr_engine = OMREngine()
