from __future__ import annotations

from datetime import date
from pathlib import Path

from cover_letter_manager.metadata import load_prop
from cover_letter_manager.paths import safe_component
from cover_letter_manager.repository import CoverLetterRepository, CreateEntryRequest


def test_safe_component_removes_path_separators() -> None:
    assert safe_component('A/B\\C:*?"<>|') == "A-B-C"
    assert safe_component("CON") == "_CON"


def test_create_and_scan_text_entry(tmp_path: Path) -> None:
    source = tmp_path / "letter.txt"
    source.write_text("I built distributed Python services and reliable APIs.", encoding="utf-8")
    root = tmp_path / "library"
    repository = CoverLetterRepository(root)

    entry = repository.create_entry(
        CreateEntryRequest(
            company="Example Corp",
            position="Backend Engineer",
            application_date=date(2026, 8, 15),
            source_file=source,
            extra={"status": "draft", "job_url": "https://example.test/job/1"},
        )
    )

    assert entry.folder == root / "Example Corp" / "Backend Engineer"
    assert entry.original_path.exists()
    assert entry.original_path.suffix == ".txt"
    assert entry.pdf_path.exists()
    assert entry.pdf_path.read_bytes().startswith(b"%PDF")
    assert entry.prop_path.exists()

    loaded = load_prop(entry.prop_path)
    assert loaded.company == "Example Corp"
    assert loaded.position == "Backend Engineer"
    assert loaded.extra["status"] == "draft"

    result = repository.scan()
    assert len(result.entries) == 1
    assert not result.warnings
    assert result.entries[0].entry_id == entry.entry_id
