from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np

from cover_letter_manager.repository import CoverLetterRepository, CreateEntryRequest
from cover_letter_manager.semantic import SemanticIndex


class FakeEmbeddingModel:
    terms = ("python", "distributed", "react", "frontend", "backend")

    def encode(self, texts, **_kwargs):
        rows = []
        for text in texts:
            lowered = text.casefold()
            vector = np.asarray([lowered.count(term) for term in self.terms], dtype=np.float32)
            norm = np.linalg.norm(vector)
            if norm:
                vector = vector / norm
            rows.append(vector)
        return np.vstack(rows)


def _create_text_entry(
    repository: CoverLetterRepository,
    temporary: Path,
    *,
    company: str,
    position: str,
    filename: str,
    text: str,
):
    source = temporary / filename
    source.write_text(text, encoding="utf-8")
    return repository.create_entry(
        CreateEntryRequest(
            company=company,
            position=position,
            application_date=date(2026, 8, 15),
            source_file=source,
        )
    )


def test_semantic_index_persists_and_ranks_entries(tmp_path: Path) -> None:
    repository = CoverLetterRepository(tmp_path / "library")
    backend = _create_text_entry(
        repository,
        tmp_path,
        company="Systems Inc",
        position="Backend Engineer",
        filename="backend.txt",
        text="I built distributed Python backend services and reliable APIs.",
    )
    _create_text_entry(
        repository,
        tmp_path,
        company="Design Inc",
        position="Frontend Engineer",
        filename="frontend.txt",
        text="I built accessible React frontend components and design systems.",
    )

    index = SemanticIndex(repository.root, model_name="fake-test-model")
    index._model = FakeEmbeddingModel()
    rows = index.rebuild(repository.scan().entries)
    assert rows >= 2
    assert index.manifest_path.exists()
    assert index.vectors_path.exists()

    ranked = index.search(repository.scan().entries, "distributed Python backend")
    assert ranked[0][0] == backend.entry_id

    cached_index = SemanticIndex(repository.root, model_name="fake-test-model")
    cached_index._model = FakeEmbeddingModel()
    cached_ranked = cached_index.search(repository.scan().entries, "distributed Python backend")
    assert cached_ranked[0][0] == backend.entry_id
