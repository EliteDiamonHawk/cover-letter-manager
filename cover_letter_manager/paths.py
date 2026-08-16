from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path

_INVALID_WINDOWS_CHARS = set('<>:"/\\|?*')
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_component(value: str, *, fallback: str = "Untitled", max_length: int = 100) -> str:
    """Return a readable, cross-platform-safe directory or filename component."""

    normalized = unicodedata.normalize("NFKC", value).strip()
    cleaned_chars: list[str] = []
    for char in normalized:
        if ord(char) < 32 or char in _INVALID_WINDOWS_CHARS:
            cleaned_chars.append("-")
        else:
            cleaned_chars.append(char)
    cleaned = "".join(cleaned_chars)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned).strip(" .-")
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in _RESERVED_WINDOWS_NAMES:
        cleaned = f"_{cleaned}"
    cleaned = cleaned[:max_length].rstrip(" .")
    return cleaned or fallback


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding=encoding)
    os.replace(temporary, path)


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
