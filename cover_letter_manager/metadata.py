from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path
from typing import Mapping

import tomlkit

from .models import CoverLetterEntry
from .paths import atomic_write_text

PROP_SCHEMA_VERSION = 1


class MetadataError(ValueError):
    pass


def _safe_file_name(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text or Path(text).name != text:
        raise MetadataError(f"Invalid {field_name!r} value in metadata: {text!r}")
    return text


def write_prop(
    path: Path,
    *,
    entry_id: str,
    company: str,
    position: str,
    application_date: date,
    created_at: str,
    source_name: str,
    original_file: str,
    pdf_file: str,
    extra: Mapping[str, str] | None = None,
) -> None:
    document = tomlkit.document()
    document.add("schema_version", PROP_SCHEMA_VERSION)
    document.add("id", entry_id)
    document.add("company", company)
    document.add("position", position)
    document.add("date", application_date.isoformat())
    document.add("created_at", created_at)
    document.add("source_name", source_name)
    document.add("original_file", original_file)
    document.add("pdf_file", pdf_file)

    extra_table = tomlkit.table()
    for key, value in sorted((extra or {}).items(), key=lambda item: item[0].casefold()):
        clean_key = str(key).strip()
        if clean_key:
            extra_table.add(clean_key, str(value))
    document.add("extra", extra_table)

    atomic_write_text(path, tomlkit.dumps(document))


def load_prop(path: Path) -> CoverLetterEntry:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise MetadataError(f"Could not read {path}: {exc}") from exc

    try:
        schema_version = int(payload.get("schema_version", 0))
        if schema_version != PROP_SCHEMA_VERSION:
            raise MetadataError(
                f"Unsupported schema_version {schema_version} in {path.name}; "
                f"expected {PROP_SCHEMA_VERSION}."
            )

        application_date = date.fromisoformat(str(payload["date"]))
        extra_payload = payload.get("extra", {})
        if not isinstance(extra_payload, dict):
            raise MetadataError(f"The [extra] value in {path.name} must be a table.")
        extra = {str(key): str(value) for key, value in extra_payload.items()}

        return CoverLetterEntry(
            entry_id=str(payload["id"]),
            company=str(payload["company"]),
            position=str(payload["position"]),
            application_date=application_date,
            created_at=str(payload["created_at"]),
            source_name=str(payload.get("source_name", "")),
            original_file=_safe_file_name(payload["original_file"], "original_file"),
            pdf_file=_safe_file_name(payload["pdf_file"], "pdf_file"),
            prop_path=path.resolve(),
            extra=extra,
        )
    except KeyError as exc:
        raise MetadataError(f"Missing required key {exc.args[0]!r} in {path.name}.") from exc
    except ValueError as exc:
        if isinstance(exc, MetadataError):
            raise
        raise MetadataError(f"Invalid value in {path.name}: {exc}") from exc
