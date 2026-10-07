from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path, PurePosixPath


_DATE_PATTERNS = [
    (re.compile(r"(?<!\d)(20\d{2})([-_.]?)(0[1-9]|1[0-2])\2(0[1-9]|[12]\d|3[01])(?!\d)"), ("%Y", "%m", "%d")),
    (re.compile(r"(?<!\d)(0[1-9]|[12]\d|3[01])([-_.])(0[1-9]|1[0-2])\2(20\d{2})(?!\d)"), ("%d", "%m", "%Y")),
]
_DAY_OFFSET = re.compile(r"\(%d([+-]\d{1,4})\)|%d([+-]\d{1,4})(?!\d)")


def normalize_relative(value: str) -> str:
    value = str(value or "").replace("\\", "/").strip().strip("/")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Ścieżka musi znajdować się w katalogu audycji")
    return "" if value in {"", "."} else path.as_posix()


def render_pattern(pattern: str, day: dt.date) -> str:
    normalized = normalize_relative(pattern)
    rendered_day, normalized = pattern_day(normalized, day)
    return rendered_day.strftime(normalized).replace("/", os.sep)


def pattern_day(pattern: str, day: dt.date) -> tuple[dt.date, str]:
    """Resolve ``(%d-1)`` or ``%d-1`` style day offset for the whole date."""
    matches = list(_DAY_OFFSET.finditer(pattern))
    if not matches:
        return day, pattern
    offsets = {int(match.group(1) or match.group(2)) for match in matches}
    if len(offsets) != 1:
        raise ValueError("Jeden schemat nie może zawierać różnych przesunięć daty")
    offset = offsets.pop()
    shifted = day + dt.timedelta(days=offset)
    return shifted, _DAY_OFFSET.sub("%d", pattern)


def safe_join(root: Path, relative: str) -> Path:
    root = root.resolve()
    target = (root / normalize_relative(relative)).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Ścieżka wychodzi poza katalog audycji")
    return target


def _replace_date(text: str) -> str:
    for regex, replacements in _DATE_PATTERNS:
        match = regex.search(text)
        if not match:
            continue
        groups = list(match.groups())
        separator = groups[1]
        if replacements[0] == "%Y":
            replacement = replacements[0] + separator + replacements[1] + separator + replacements[2]
        else:
            replacement = replacements[0] + separator + replacements[1] + separator + replacements[2]
        return text[: match.start()] + replacement + text[match.end() :]
    return text


def infer_patterns(relative_path: str) -> dict[str, str]:
    """Infer strftime masks from one selected file below MEDIA_ROOT."""
    normalized = normalize_relative(relative_path)
    path = PurePosixPath(normalized)
    if not path.name:
        raise ValueError("Wybierz plik")

    filename = _replace_date(path.name)
    folder_parts = list(path.parent.parts) if str(path.parent) != "." else []
    replaced_parts: list[str] = []
    for index, part in enumerate(folder_parts):
        replaced = _replace_date(part)
        if replaced == part and re.fullmatch(r"20\d{2}", part):
            replaced = "%Y"
        elif replaced == part and re.fullmatch(r"0[1-9]|1[0-2]", part):
            previous = replaced_parts[-1] if replaced_parts else ""
            if "%Y" in previous or previous == "%Y":
                replaced = "%m"
        replaced_parts.append(replaced)
    return {
        "folder_pattern": "/".join(replaced_parts),
        "filename_pattern": filename,
    }


def preview_path(folder_pattern: str, filename_pattern: str, day: dt.date) -> str:
    folder_day, folder_mask = pattern_day(normalize_relative(folder_pattern), day)
    filename_day, filename_mask = pattern_day(normalize_relative(filename_pattern), day)
    folder = folder_day.strftime(folder_mask)
    filename = filename_day.strftime(filename_mask)
    return PurePosixPath(folder, filename).as_posix()
