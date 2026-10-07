from __future__ import annotations

import datetime as dt
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

SPY_FILENAME = re.compile(r"^rec_(\d{8})-(\d{6})\.(mp3|wav|flac|m4a|ogg)$", re.IGNORECASE)
SPY_FILENAME_SPACED = re.compile(
    r"^(\d{4}) (\d{2}) (\d{2}) (\d{2}) (\d{2}) (\d{2})(?: \d+)?\.(mp3|wav|flac|m4a|ogg)$",
    re.IGNORECASE,
)
TIMECODE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})$")
MAX_CLIP_SECONDS = 180 * 60
RECORDING_EDGE_TOLERANCE_SECONDS = 5


def parse_timecode(value: str) -> dt.time:
    match = TIMECODE.fullmatch(str(value).strip())
    if not match:
        raise ValueError("Godzinę wpisz jako HH:MM:SS, np. 12:54:00")
    hour, minute, second = map(int, match.groups())
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError("Nieprawidłowa godzina — użyj formatu 24-godzinnego HH:MM:SS")
    return dt.time(hour, minute, second)


def _audio_duration(path: Path) -> float:
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(path)
        if audio is not None and getattr(audio, "info", None) is not None:
            return max(0.0, float(audio.info.length))
    # Mutagen uses format-specific exception classes for an incomplete file
    # that the recorder is still writing.  One such file must not break the
    # whole Spy listing; use the normal one-hour fallback until metadata is
    # readable.
    except Exception:
        pass
    return 3600.0


def _file_info(path: Path) -> dict[str, Any] | None:
    match = SPY_FILENAME.fullmatch(path.name)
    spaced_match = SPY_FILENAME_SPACED.fullmatch(path.name)
    if (not match and not spaced_match) or not path.is_file():
        return None
    try:
        if match:
            started_at = dt.datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
        else:
            assert spaced_match is not None
            started_at = dt.datetime(*map(int, spaced_match.groups()[:6]))
    except ValueError:
        return None
    duration_seconds = _audio_duration(path)
    return {
        "name": path.name,
        "path": path.name,
        "started_at": started_at.isoformat(),
        "start_time": started_at.strftime("%H:%M:%S"),
        "end_time": (started_at + dt.timedelta(seconds=duration_seconds)).strftime("%H:%M:%S"),
        "duration_seconds": round(duration_seconds, 3),
        "size": path.stat().st_size,
        "_path": path,
        "_started_at": started_at,
    }


def _is_rec_file(item: dict[str, Any]) -> bool:
    return str(item["name"]).casefold().startswith("rec_")


def _recording_end(item: dict[str, Any]) -> dt.datetime:
    return item["_started_at"] + dt.timedelta(seconds=float(item["duration_seconds"]))


def _prefer_rec_files(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Choose one coherent recording for each hour.

    The current ``rec_*`` file wins when it covers the same range as the legacy
    hourly file. If ``rec_*`` is shorter, starts late or was split after an
    interruption, the complete legacy recording is safer and replaces all
    ``rec_*`` fragments from that hour.
    """
    hourly: dict[dt.datetime, list[dict[str, Any]]] = {}
    for item in items:
        hour = item["_started_at"].replace(minute=0, second=0, microsecond=0)
        hourly.setdefault(hour, []).append(item)

    selected: list[dict[str, Any]] = []
    tolerance = dt.timedelta(seconds=RECORDING_EDGE_TOLERANCE_SECONDS)
    for hour in sorted(hourly):
        group = hourly[hour]
        rec_items = sorted(
            (item for item in group if _is_rec_file(item)),
            key=lambda item: (item["_started_at"], item["name"].casefold()),
        )
        legacy_items = sorted(
            (item for item in group if not _is_rec_file(item)),
            key=lambda item: (-float(item["duration_seconds"]), item["name"].casefold()),
        )
        if not legacy_items:
            selected.extend(rec_items)
            continue
        legacy = legacy_items[0]
        if not rec_items:
            selected.append(legacy)
            continue

        complete_rec = rec_items[0]
        rec_is_coherent = (
            len(rec_items) == 1
            and complete_rec["_started_at"] <= legacy["_started_at"] + tolerance
            and _recording_end(complete_rec) >= _recording_end(legacy) - tolerance
        )
        selected.append(complete_rec if rec_is_coherent else legacy)
    return sorted(selected, key=lambda item: (item["_started_at"], item["name"].casefold()))


def list_spy_files(root: Path, day: dt.date) -> list[dict[str, Any]]:
    if not root.is_dir():
        raise FileNotFoundError("Folder Szpiega nie jest dostępny")
    items: list[dict[str, Any]] = []
    try:
        paths = sorted(
            {*root.glob(f"rec_{day:%Y%m%d}-*"), *root.glob(f"{day:%Y %m %d} *")},
            key=lambda path: path.name.casefold(),
        )
    except OSError as exc:
        raise PermissionError(f"Brak dostępu do folderu Szpiega: {exc}") from exc
    found: list[dict[str, Any]] = []
    for path in paths:
        info = _file_info(path)
        if info:
            found.append(info)
    for info in _prefer_rec_files(found):
        info.pop("_path", None)
        info.pop("_started_at", None)
        items.append(info)
    return items


def _scan_range(root: Path, start: dt.datetime, end: dt.datetime) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    day = start.date()
    while day <= end.date():
        paths = {*root.glob(f"rec_{day:%Y%m%d}-*"), *root.glob(f"{day:%Y %m %d} *")}
        for path in paths:
            info = _file_info(path)
            if info:
                candidates.append(info)
        day += dt.timedelta(days=1)
    return _prefer_rec_files(candidates)


def _safe_output_name(value: str, start: dt.datetime, end: dt.datetime) -> str:
    raw = str(value or "").strip()
    if raw.lower().endswith(".mp3"):
        raw = raw[:-4]
    raw = re.sub(r"[^0-9A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż._ -]+", "_", raw).strip(" ._")
    if not raw:
        raw = f"szpieg_{start:%Y%m%d_%H%M%S}-{end:%Y%m%d_%H%M%S}"
    return f"{raw[:180]}.mp3"


def create_spy_clip(
    root: Path,
    day: dt.date,
    start_time: str,
    end_time: str,
    output_dir: Path,
    output_name: str = "",
) -> Path:
    if not root.is_dir():
        raise FileNotFoundError("Folder Szpiega nie jest dostępny")
    start = dt.datetime.combine(day, parse_timecode(start_time))
    end = dt.datetime.combine(day, parse_timecode(end_time))
    if end <= start:
        end += dt.timedelta(days=1)
    length = (end - start).total_seconds()
    if length <= 0:
        raise ValueError("Koniec wycinka musi być później niż początek")
    if length > MAX_CLIP_SECONDS:
        raise ValueError("Wycinek może mieć maksymalnie 180 minut")

    candidates = _scan_range(root, start, end)
    segments: list[tuple[Path, float, float]] = []
    covered_until = start
    for item in candidates:
        file_start = item["_started_at"]
        file_end = file_start + dt.timedelta(seconds=float(item["duration_seconds"]))
        overlap_start = max(start, file_start, covered_until)
        overlap_end = min(end, file_end)
        if overlap_end <= overlap_start:
            continue
        if overlap_start > covered_until + dt.timedelta(seconds=2):
            missing = covered_until.strftime("%H:%M:%S")
            raise FileNotFoundError(f"Brakuje nagrania obejmującego godzinę {missing}")
        offset = max(0.0, (overlap_start - file_start).total_seconds())
        duration = (overlap_end - overlap_start).total_seconds()
        segments.append((item["_path"], offset, duration))
        covered_until = max(covered_until, overlap_end)
        if covered_until >= end - dt.timedelta(seconds=0.25):
            break
    if not segments or covered_until < end - dt.timedelta(seconds=2):
        raise FileNotFoundError("Brakuje pliku lub fragmentu nagrania dla wybranego zakresu")

    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{uuid.uuid4().hex}_{_safe_output_name(output_name, start, end)}"
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for source, offset, duration in segments:
        command.extend(["-ss", f"{offset:.3f}", "-t", f"{duration:.3f}", "-i", str(source)])
    filters = []
    labels = []
    for index in range(len(segments)):
        label = f"a{index}"
        filters.append(f"[{index}:a]aresample=48000,asetpts=PTS-STARTPTS[{label}]")
        labels.append(f"[{label}]")
    filters.append(f"{''.join(labels)}concat=n={len(segments)}:v=0:a=1[out]")
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[out]",
        "-codec:a", "libmp3lame", "-b:a", "192k", str(target),
    ])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30 * 60)
    except FileNotFoundError as exc:
        raise RuntimeError("W obrazie Dockera brakuje programu ffmpeg") from exc
    except subprocess.TimeoutExpired as exc:
        target.unlink(missing_ok=True)
        raise RuntimeError("Wycinanie trwało zbyt długo i zostało przerwane") from exc
    if completed.returncode != 0:
        target.unlink(missing_ok=True)
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "nieznany błąd"
        raise RuntimeError(f"Nie udało się wyciąć nagrania: {detail}")
    if not target.is_file() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg nie utworzył pliku wynikowego")
    return target
