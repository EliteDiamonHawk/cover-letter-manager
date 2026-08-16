from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping

from .metadata import MetadataError, load_prop, write_prop
from .models import CoverLetterEntry, ScanResult
from .paths import safe_component
from .pdf_convert import SUPPORTED_INPUT_EXTENSIONS, convert_to_pdf


@dataclass(frozen=True, slots=True)
class CreateEntryRequest:
    company: str
    position: str
    application_date: date
    source_file: Path
    extra: Mapping[str, str] = field(default_factory=dict)


class RepositoryError(RuntimeError):
    pass


class CoverLetterRepository:
    """Filesystem-backed repository using root/company/position."""

    INTERNAL_DIRECTORY = ".coverletter_manager"

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise RepositoryError(f"Not a directory: {self.root}")
        self.internal_dir = self.root / self.INTERNAL_DIRECTORY
        self.internal_dir.mkdir(exist_ok=True)

    def scan(self) -> ScanResult:
        entries: list[CoverLetterEntry] = []
        warnings: list[str] = []
        for prop_path in self.root.rglob("*.prop"):
            if self.internal_dir == prop_path or self.internal_dir in prop_path.parents:
                continue
            try:
                entry = load_prop(prop_path)
                if not entry.original_path.exists():
                    warnings.append(f"Missing original file for {prop_path}")
                if not entry.pdf_path.exists():
                    warnings.append(f"Missing PDF file for {prop_path}")
                entries.append(entry)
            except MetadataError as exc:
                warnings.append(str(exc))

        entries.sort(
            key=lambda item: (item.application_date, item.company.casefold(), item.position.casefold()),
            reverse=True,
        )
        return ScanResult(entries=tuple(entries), warnings=tuple(warnings))

    def create_entry(self, request: CreateEntryRequest) -> CoverLetterEntry:
        company = request.company.strip()
        position = request.position.strip()
        source = request.source_file.expanduser().resolve()
        if not company:
            raise RepositoryError("Company is required.")
        if not position:
            raise RepositoryError("Position is required.")
        if not source.exists() or not source.is_file():
            raise RepositoryError(f"The selected letter does not exist: {source}")
        suffix = source.suffix.casefold()
        if suffix not in SUPPORTED_INPUT_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_INPUT_EXTENSIONS))
            raise RepositoryError(f"Unsupported file type {suffix!r}. Supported: {supported}")

        entry_id = uuid.uuid4().hex
        prefix = f"{request.application_date.isoformat()}_{entry_id[:8]}"
        original_file = f"{prefix}_original{suffix}"
        pdf_file = f"{prefix}_cover-letter.pdf"
        prop_file = f"{prefix}.prop"

        company_dir = safe_component(company, fallback="Unknown company")
        position_dir = safe_component(position, fallback="Unknown position")
        target_dir = self.root / company_dir / position_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        temp_parent = self.internal_dir / "tmp"
        temp_parent.mkdir(exist_ok=True)
        created_targets: list[Path] = []

        try:
            with tempfile.TemporaryDirectory(prefix=f"{entry_id}-", dir=temp_parent) as temp_name:
                staging = Path(temp_name)
                staged_original = staging / original_file
                staged_pdf = staging / pdf_file
                staged_prop = staging / prop_file

                shutil.copy2(source, staged_original)
                convert_to_pdf(staged_original, staged_pdf)
                created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                write_prop(
                    staged_prop,
                    entry_id=entry_id,
                    company=company,
                    position=position,
                    application_date=request.application_date,
                    created_at=created_at,
                    source_name=source.name,
                    original_file=original_file,
                    pdf_file=pdf_file,
                    extra=request.extra,
                )

                for staged_file in (staged_original, staged_pdf, staged_prop):
                    destination = target_dir / staged_file.name
                    if destination.exists():
                        raise RepositoryError(f"Refusing to overwrite existing file: {destination}")
                    os.replace(staged_file, destination)
                    created_targets.append(destination)

            return load_prop(target_dir / prop_file)
        except Exception:
            for path in reversed(created_targets):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
