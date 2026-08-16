from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from .models import CoverLetterEntry
from .paths import atomic_write_text, sha256_file
from .text_extract import TextExtractionError, extract_text

ProgressCallback = Callable[[str], None]


class SemanticSearchError(RuntimeError):
    pass


def _chunk_text(text: str, *, max_chars: int = 1100) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    if not paragraphs:
        return [""]

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            words = paragraph.split()
            pieces: list[str] = []
            piece = ""
            for word in words:
                candidate = f"{piece} {word}".strip()
                if piece and len(candidate) > max_chars:
                    pieces.append(piece)
                    piece = word
                else:
                    piece = candidate
            if piece:
                pieces.append(piece)
        else:
            pieces = [paragraph]

        for piece in pieces:
            candidate = f"{current}\n\n{piece}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]


class SemanticIndex:
    """A disposable, chunk-level Sentence Transformers index stored under the root."""

    INDEX_VERSION = 1

    def __init__(
        self,
        root: Path,
        *,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> None:
        self.root = root.resolve()
        self.model_name = model_name
        self.index_dir = self.root / ".coverletter_manager" / "semantic"
        self.manifest_path = self.index_dir / "manifest.json"
        self.vectors_path = self.index_dir / "vectors.npy"
        self._model = None

    def _load_model(self, progress: ProgressCallback | None = None):
        if self._model is not None:
            return self._model
        if progress:
            progress(f"Loading semantic model: {self.model_name}")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise SemanticSearchError(
                "sentence-transformers is not installed. Run: pip install -r requirements.txt"
            ) from exc
        try:
            self._model = SentenceTransformer(self.model_name)
        except Exception as exc:
            raise SemanticSearchError(
                f"Could not load semantic model {self.model_name!r}. "
                "The first run may require an internet connection. "
                f"Details: {exc}"
            ) from exc
        return self._model

    @staticmethod
    def _fingerprint(entry: CoverLetterEntry) -> str:
        digest = hashlib.sha256()
        for path in (entry.prop_path, entry.original_path, entry.pdf_path):
            digest.update(path.name.encode("utf-8", errors="replace"))
            if path.exists():
                digest.update(str(path.stat().st_size).encode("ascii"))
                digest.update(sha256_file(path).encode("ascii"))
            else:
                digest.update(b"missing")
        return digest.hexdigest()

    @staticmethod
    def _metadata_prefix(entry: CoverLetterEntry) -> str:
        lines = [
            f"Company: {entry.company}",
            f"Position: {entry.position}",
            f"Application date: {entry.application_date.isoformat()}",
        ]
        for key, value in sorted(entry.extra.items(), key=lambda item: item[0].casefold()):
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def _document_text(self, entry: CoverLetterEntry) -> str:
        errors: list[str] = []
        for path in (entry.original_path, entry.pdf_path):
            if not path.exists():
                continue
            try:
                text = extract_text(path)
                if text:
                    return text
            except TextExtractionError as exc:
                errors.append(str(exc))
        if errors:
            return ""
        return ""

    def _build_rows(
        self,
        entries: Iterable[CoverLetterEntry],
        progress: ProgressCallback | None,
    ) -> tuple[list[str], list[dict[str, object]]]:
        corpus: list[str] = []
        rows: list[dict[str, object]] = []
        entries_list = list(entries)
        for number, entry in enumerate(entries_list, start=1):
            if progress:
                progress(f"Reading {number}/{len(entries_list)}: {entry.company} - {entry.position}")
            text = self._document_text(entry)
            chunks = _chunk_text(text)
            prefix = self._metadata_prefix(entry)
            for chunk_index, chunk in enumerate(chunks):
                corpus.append(f"{prefix}\n\nCover letter excerpt:\n{chunk}".strip())
                rows.append({"entry_id": entry.entry_id, "chunk": chunk_index})
        return corpus, rows

    def _load_cached(
        self,
        fingerprints: dict[str, str],
    ) -> tuple[np.ndarray, list[dict[str, object]]] | None:
        if not self.manifest_path.exists() or not self.vectors_path.exists():
            return None
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if manifest.get("index_version") != self.INDEX_VERSION:
                return None
            if manifest.get("model") != self.model_name:
                return None
            if manifest.get("fingerprints") != fingerprints:
                return None
            rows = manifest.get("rows")
            if not isinstance(rows, list):
                return None
            vectors = np.load(self.vectors_path, allow_pickle=False)
            if vectors.ndim != 2 or vectors.shape[0] != len(rows):
                return None
            return vectors.astype(np.float32, copy=False), rows
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def ensure_index(
        self,
        entries: Iterable[CoverLetterEntry],
        *,
        force: bool = False,
        progress: ProgressCallback | None = None,
    ) -> tuple[np.ndarray, list[dict[str, object]]]:
        entries_list = sorted(entries, key=lambda entry: entry.entry_id)
        fingerprints = {entry.entry_id: self._fingerprint(entry) for entry in entries_list}
        if not force:
            cached = self._load_cached(fingerprints)
            if cached is not None:
                if progress:
                    progress("Using the current semantic index.")
                return cached

        if not entries_list:
            return np.empty((0, 0), dtype=np.float32), []

        corpus, rows = self._build_rows(entries_list, progress)
        model = self._load_model(progress)
        if progress:
            progress(f"Embedding {len(corpus)} text chunks...")
        try:
            vectors = model.encode(
                corpus,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise SemanticSearchError(f"Could not build semantic embeddings: {exc}") from exc
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)

        self.index_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "index_version": self.INDEX_VERSION,
            "model": self.model_name,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fingerprints": fingerprints,
            "rows": rows,
            "dimensions": int(vectors.shape[1]),
        }

        with tempfile.NamedTemporaryFile(
            mode="wb", prefix="vectors-", suffix=".npy", dir=self.index_dir, delete=False
        ) as temporary_file:
            temporary_vectors = Path(temporary_file.name)
            np.save(temporary_file, vectors, allow_pickle=False)
        try:
            os.replace(temporary_vectors, self.vectors_path)
            atomic_write_text(self.manifest_path, json.dumps(manifest, indent=2, sort_keys=True))
        finally:
            temporary_vectors.unlink(missing_ok=True)

        if progress:
            progress("Semantic index is ready.")
        return vectors, rows

    def rebuild(
        self,
        entries: Iterable[CoverLetterEntry],
        *,
        progress: ProgressCallback | None = None,
    ) -> int:
        vectors, _ = self.ensure_index(entries, force=True, progress=progress)
        return int(vectors.shape[0])

    def search(
        self,
        entries: Iterable[CoverLetterEntry],
        query: str,
        *,
        top_k: int = 100,
        progress: ProgressCallback | None = None,
    ) -> list[tuple[str, float]]:
        clean_query = query.strip()
        if not clean_query:
            return []

        vectors, rows = self.ensure_index(entries, progress=progress)
        if vectors.size == 0 or not rows:
            return []

        model = self._load_model(progress)
        if progress:
            progress("Searching semantic index...")
        try:
            query_vector = model.encode(
                [clean_query],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise SemanticSearchError(f"Could not encode the search query: {exc}") from exc

        query_array = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)
        if query_array.shape[1] != vectors.shape[1]:
            raise SemanticSearchError("The semantic index dimensions do not match the current model.")
        scores = vectors @ query_array[0]

        best_by_entry: dict[str, float] = defaultdict(lambda: float("-inf"))
        for row, score in zip(rows, scores, strict=True):
            entry_id = str(row["entry_id"])
            best_by_entry[entry_id] = max(best_by_entry[entry_id], float(score))

        ranked = sorted(best_by_entry.items(), key=lambda item: item[1], reverse=True)
        return ranked[: max(1, top_k)]
