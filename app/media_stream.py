from __future__ import annotations

from pathlib import Path
from typing import Iterator


CHUNK_SIZE = 1024 * 1024


def parse_byte_range(value: str | None, size: int) -> tuple[int, int] | None:
    if not value:
        return None
    if size <= 0 or not value.lower().startswith("bytes=") or "," in value:
        raise ValueError("Nieprawidłowy zakres pliku")
    raw = value.split("=", 1)[1].strip()
    if "-" not in raw:
        raise ValueError("Nieprawidłowy zakres pliku")
    start_text, end_text = raw.split("-", 1)
    try:
        if not start_text:
            suffix = int(end_text)
            if suffix <= 0:
                raise ValueError
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except ValueError as exc:
        raise ValueError("Nieprawidłowy zakres pliku") from exc
    if start < 0 or start >= size or end < start:
        raise ValueError("Zakres wykracza poza plik")
    return start, min(end, size - 1)


def file_chunks(path: Path, start: int, end: int) -> Iterator[bytes]:
    remaining = end - start + 1
    with path.open("rb") as source:
        source.seek(start)
        while remaining > 0:
            block = source.read(min(CHUNK_SIZE, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block
