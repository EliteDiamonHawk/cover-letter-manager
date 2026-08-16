from cover_letter_manager.semantic import _chunk_text


def test_chunk_text_keeps_small_paragraphs() -> None:
    chunks = _chunk_text("First paragraph.\n\nSecond paragraph.", max_chars=100)
    assert chunks == ["First paragraph.\n\nSecond paragraph."]


def test_chunk_text_splits_long_content() -> None:
    text = " ".join(["word"] * 100)
    chunks = _chunk_text(text, max_chars=80)
    assert len(chunks) > 1
    assert all(len(chunk) <= 80 for chunk in chunks)
