from __future__ import annotations

import html
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .text_extract import extract_text

SUPPORTED_INPUT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".odt",
    ".rtf",
    ".txt",
    ".md",
    ".markdown",
    ".html",
    ".htm",
}

_TEXT_FORMATS = {".txt", ".md", ".markdown", ".html", ".htm"}


class ConversionError(RuntimeError):
    pass


def find_libreoffice() -> Path | None:
    for executable in ("libreoffice", "soffice"):
        found = shutil.which(executable)
        if found:
            return Path(found)

    candidates: list[Path] = []
    if sys.platform.startswith("win"):
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(variable)
            if base:
                candidates.append(Path(base) / "LibreOffice" / "program" / "soffice.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))

    return next((candidate for candidate in candidates if candidate.exists()), None)


def _plain_text_to_pdf(source: Path, destination: Path) -> None:
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    try:
        body = extract_text(source)
    except Exception as exc:
        raise ConversionError(f"Could not read {source.name}: {exc}") from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "CoverLetterBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=11,
        leading=15,
        alignment=TA_LEFT,
        spaceAfter=8,
    )
    title_style = ParagraphStyle(
        "CoverLetterTitle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        spaceAfter=14,
    )
    document = SimpleDocTemplate(
        str(destination),
        pagesize=LETTER,
        rightMargin=0.8 * inch,
        leftMargin=0.8 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=source.stem,
    )

    story = [Paragraph(html.escape(source.stem), title_style)]
    paragraphs = [part.strip() for part in body.split("\n\n") if part.strip()]
    if not paragraphs:
        paragraphs = [""]
    for paragraph in paragraphs:
        escaped = html.escape(paragraph).replace("\n", "<br/>")
        story.append(Paragraph(escaped, body_style))
        story.append(Spacer(1, 4))
    document.build(story)


def _office_to_pdf(source: Path, destination: Path) -> None:
    executable = find_libreoffice()
    if executable is None:
        raise ConversionError(
            "LibreOffice was not found. Install LibreOffice or add soffice/libreoffice "
            "to PATH to convert DOC, DOCX, ODT, or RTF files."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="clm-convert-") as temporary_dir:
        temporary = Path(temporary_dir)
        output_dir = temporary / "output"
        profile_dir = temporary / "profile"
        output_dir.mkdir()
        profile_dir.mkdir()

        command = [
            str(executable),
            "--headless",
            f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(source.resolve()),
        ]
        creation_flags = 0
        if sys.platform.startswith("win") and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation_flags = subprocess.CREATE_NO_WINDOW

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                creationflags=creation_flags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ConversionError(f"LibreOffice conversion failed: {exc}") from exc

        expected = output_dir / f"{source.stem}.pdf"
        if not expected.exists():
            candidates = list(output_dir.glob("*.pdf"))
            if len(candidates) == 1:
                expected = candidates[0]
            else:
                details = (completed.stdout + "\n" + completed.stderr).strip()
                raise ConversionError(
                    f"LibreOffice did not produce a PDF for {source.name}. "
                    f"Exit code: {completed.returncode}. {details}"
                )
        shutil.copy2(expected, destination)


def convert_to_pdf(source: Path, destination: Path) -> None:
    """Convert a supported cover-letter file to PDF."""

    source = source.resolve()
    destination = destination.resolve()
    if not source.exists() or not source.is_file():
        raise ConversionError(f"Source file does not exist: {source}")

    suffix = source.suffix.casefold()
    if suffix not in SUPPORTED_INPUT_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_INPUT_EXTENSIONS))
        raise ConversionError(f"Unsupported source format {suffix!r}. Supported formats: {supported}")

    if suffix == ".pdf":
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    elif suffix in _TEXT_FORMATS:
        _plain_text_to_pdf(source, destination)
    else:
        _office_to_pdf(source, destination)

    if not destination.exists() or destination.stat().st_size == 0:
        raise ConversionError(f"PDF conversion did not create a valid file: {destination}")
