from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class CoverLetterEntry:
    """One cover-letter entry described by a .prop sidecar file."""

    entry_id: str
    company: str
    position: str
    application_date: date
    created_at: str
    source_name: str
    original_file: str
    pdf_file: str
    prop_path: Path
    extra: Mapping[str, str] = field(default_factory=dict)

    @property
    def folder(self) -> Path:
        return self.prop_path.parent

    @property
    def original_path(self) -> Path:
        return self.folder / self.original_file

    @property
    def pdf_path(self) -> Path:
        return self.folder / self.pdf_file


@dataclass(frozen=True, slots=True)
class ScanResult:
    entries: tuple[CoverLetterEntry, ...]
    warnings: tuple[str, ...]
