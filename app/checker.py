from __future__ import annotations

import datetime as dt
import errno
import os
import shutil
import tempfile
import wave
import zipfile
from pathlib import Path
from typing import Any

from .ftp_sync import ftp_source_status
from .patterns import preview_path, safe_join
from .schedules import matches_date


SOURCE_LOOKBACK_DAYS = 62
AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}


def readable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with path.open("rb") as source:
            source.read(1)
    except OSError:
        return False
    return True


def audio_duration(path: Path) -> tuple[int | None, str | None]:
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(path)
        if audio is not None and getattr(audio, "info", None) is not None:
            seconds = int(round(float(audio.info.length)))
            return seconds, f"{seconds // 60:02d}:{seconds % 60:02d}"
    except Exception:
        pass

    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as audio:
                seconds = int(round(audio.getnframes() / audio.getframerate()))
                return seconds, f"{seconds // 60:02d}:{seconds % 60:02d}"
        except (wave.Error, OSError, ZeroDivisionError):
            pass
    return None, None


def _patterns(occurrence: dict[str, Any]) -> list[str]:
    values = occurrence.get("filename_patterns") or [occurrence["filename_pattern"]]
    return [str(value) for value in values if str(value).strip()]


def _path_for(
    occurrence: dict[str, Any], day: dt.date, media_root: Path, part_index: int = 0
) -> tuple[str, Path]:
    patterns = _patterns(occurrence)
    relative = preview_path(occurrence["folder_pattern"], patterns[part_index], day)
    return relative.replace(os.sep, "/"), safe_join(media_root, relative)


def _youtube_relative(relative: str) -> str:
    path = Path(relative)
    return str(path.with_name(f"{path.stem}_yt{path.suffix}")).replace(os.sep, "/")


def latest_scheduled_premiere_day(show: dict[str, Any], day: dt.date) -> dt.date | None:
    premiere_slots = show.get("premiere_slots") or []
    for offset in range(SOURCE_LOOKBACK_DAYS + 1):
        candidate_day = day - dt.timedelta(days=offset)
        if premiere_slots:
            if any(matches_date(slot.get("schedule", []), candidate_day) for slot in premiere_slots):
                return candidate_day
        elif matches_date(show.get("schedule", []), candidate_day):
            return candidate_day
    return None


def scheduled_premiere_source(
    show: dict[str, Any], source_day: dt.date | None, media_root: Path, part_index: int = 0
) -> tuple[dt.date, str, Path] | None:
    if source_day is None:
        return None
    relative, path = _path_for(show, source_day, media_root, part_index)
    return source_day, relative, path


def check_occurrence(
    show: dict[str, Any],
    occurrence: dict[str, Any],
    day: dt.date,
    media_root: Path,
    repeat_index: int | None = None,
    emission_times: list[str] | None = None,
) -> dict[str, Any]:
    patterns = _patterns(occurrence)
    is_repeat = repeat_index is not None
    source_day = latest_scheduled_premiere_day(show, day) if is_repeat else day
    browse_relative, _ = _path_for(show, source_day or day, media_root, 0)
    browse_parent = Path(browse_relative).parent.as_posix()
    if browse_parent == ".":
        browse_parent = ""
    parts: list[dict[str, Any]] = []
    for part_index in range(len(patterns)):
        relative, target = _path_for(occurrence, day, media_root, part_index)
        part_found = readable_file(target)
        duration_seconds: int | None = None
        duration: str | None = None
        if part_found:
            duration_seconds, duration = audio_duration(target)
        source = scheduled_premiere_source(show, source_day, media_root, part_index) if is_repeat and not part_found else None
        parts.append(
            {
                "part_number": part_index + 1,
                "file_type": "audio",
                "label": f"cz. {part_index + 1}" if len(patterns) > 1 else "plik",
                "found": part_found,
                "relative_path": relative,
                "duration_seconds": duration_seconds,
                "duration": duration,
                "source_relative_path": source[1] if source else None,
                "can_generate": bool(source and readable_file(source[2])),
            }
        )
        if not is_repeat and show.get("has_youtube_version"):
            youtube_relative = _youtube_relative(relative)
            youtube_target = safe_join(media_root, youtube_relative)
            youtube_found = readable_file(youtube_target)
            youtube_seconds: int | None = None
            youtube_duration: str | None = None
            if youtube_found:
                youtube_seconds, youtube_duration = audio_duration(youtube_target)
            parts.append(
                {
                    "part_number": part_index + 1,
                    "file_type": "youtube",
                    "label": "YT" if len(patterns) == 1 else f"YT cz. {part_index + 1}",
                    "found": youtube_found,
                    "relative_path": youtube_relative,
                    "duration_seconds": youtube_seconds,
                    "duration": youtube_duration,
                    "source_relative_path": None,
                    "can_generate": False,
                }
            )
    found = all(part["found"] for part in parts)
    files_found = sum(1 for part in parts if part["found"])
    missing_parts = [part for part in parts if not part["found"]]
    audio_parts = [part for part in parts if part["file_type"] == "audio"]
    actual_duration_seconds: int | None = None
    actual_duration: str | None = None
    if audio_parts and all(
        part["found"] and part["duration_seconds"] is not None for part in audio_parts
    ):
        actual_duration_seconds = sum(int(part["duration_seconds"]) for part in audio_parts)
        actual_duration = (
            f"{actual_duration_seconds // 60:02d}:{actual_duration_seconds % 60:02d}"
        )
    max_duration_minutes = show.get("max_duration_minutes")
    duration_exceeded = bool(
        actual_duration_seconds is not None
        and max_duration_minutes is not None
        and actual_duration_seconds > round(float(max_duration_minutes) * 60)
    )
    ftp_sources: list[dict[str, Any]] = []
    ftp_rename_error: str | None = None
    if show.get("is_ftp") and show.get("ftp_rename_enabled"):
        try:
            ftp_sources = ftp_source_status(show, occurrence, day, media_root)
        except ValueError as exc:
            ftp_rename_error = str(exc)
    tags = list(show.get("tags", []))
    if is_repeat:
        tags.append("powtórka")
    occurrence_times = sorted(set(emission_times or occurrence.get("emission_times") or []))
    if not occurrence_times and occurrence.get("emission_time"):
        occurrence_times = [occurrence["emission_time"]]
    return {
        "id": show["id"],
        "name": show["name"],
        "requires_editing": show.get("requires_editing", False),
        "is_ftp": show.get("is_ftp", False),
        "tags": tags,
        "occurrence_type": "repeat" if is_repeat else "main",
        "occurrence_key": f"repeat:{occurrence.get('id')}" if is_repeat else "main",
        "occurrence_label": occurrence.get("label", "Emisja główna"),
        "repeat_id": occurrence.get("id") if is_repeat else None,
        "parts_total": len(parts),
        "files_found": files_found,
        "parts": parts,
        "emission_time": occurrence_times[0] if occurrence_times else None,
        "emission_times": occurrence_times,
        "found": found,
        "status": "found" if found else "missing",
        "relative_path": parts[0]["relative_path"],
        "duration_seconds": parts[0]["duration_seconds"] if len(parts) == 1 else None,
        "duration": parts[0]["duration"] if len(parts) == 1 else None,
        "actual_duration_seconds": actual_duration_seconds,
        "actual_duration": actual_duration,
        "expected_duration_minutes": show.get("duration_minutes"),
        "max_duration_minutes": max_duration_minutes,
        "duration_exceeded": duration_exceeded,
        "can_generate": bool(is_repeat and any(part["file_type"] == "audio" for part in missing_parts)),
        "ftp_can_sync": bool(show.get("is_ftp") and show.get("ftp_source_path")),
        "ftp_rename_enabled": bool(show.get("ftp_rename_enabled")),
        "ftp_sources": ftp_sources,
        "ftp_can_rename": bool(
            ftp_sources
            and len(ftp_sources) == len(patterns)
            and all(source["found"] for source in ftp_sources)
        ),
        "ftp_renamed": bool(
            ftp_sources
            and len(ftp_sources) == len(patterns)
            and all(source.get("renamed") for source in ftp_sources)
        ),
        "ftp_rename_error": ftp_rename_error,
        "source_relative_path": next(
            (part["source_relative_path"] for part in missing_parts if part["source_relative_path"]), None
        ),
        "source_premiere_date": source_day.isoformat() if is_repeat and source_day else None,
        "source_browse_path": browse_parent,
        "send_to_author": bool(show.get("send_to_author")) and not is_repeat,
        "author_email": show.get("author_email", "") if not is_repeat else "",
        "production_watch_folders": show.get("production_watch_folders", []),
    }


def check_show(show: dict[str, Any], day: dt.date, media_root: Path) -> dict[str, Any]:
    return check_occurrence(show, show, day, media_root)


def build_report(shows: list[dict[str, Any]], day: dt.date, media_root: Path) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for show in shows:
        if not show["active"]:
            continue
        matching_slots = [
            slot for slot in show.get("premiere_slots", [])
            if matches_date(slot.get("schedule", []), day)
        ]
        if matching_slots:
            times = sorted({time for slot in matching_slots for time in slot.get("emission_times", [])})
            items.append(check_occurrence(show, show, day, media_root, emission_times=times))
        elif not show.get("premiere_slots") and matches_date(show.get("schedule", []), day):
            items.append(check_occurrence(show, show, day, media_root))
        for index, repeat in enumerate(show.get("repeats", [])):
            if matches_date(repeat["schedule"], day):
                items.append(
                    check_occurrence(
                        show, repeat, day, media_root, index,
                        emission_times=repeat.get("emission_times", []),
                    )
                )
    items.sort(key=lambda item: (item["found"], item.get("emission_time") or "99:99", item["name"].casefold()))
    found = sum(1 for item in items if item["found"])
    return {
        "date": day.isoformat(),
        "weekday": ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"][day.weekday()],
        "found": found,
        "missing": len(items) - found,
        "total": len(items),
        "items": items,
    }


def generate_repeat(
    show: dict[str, Any], repeat_id: str, day: dt.date, media_root: Path
) -> dict[str, Any]:
    if not show.get("active"):
        raise ValueError("Audycja jest nieaktywna")
    repeat = next((item for item in show.get("repeats", []) if item["id"] == repeat_id), None)
    if repeat is None:
        raise ValueError("Nie znaleziono powtórki")
    if not matches_date(repeat["schedule"], day):
        raise ValueError("Ta powtórka nie jest zaplanowana na wybrany dzień")

    repeat_patterns = _patterns(repeat)
    main_patterns = _patterns(show)
    if len(repeat_patterns) != len(main_patterns):
        raise ValueError("Powtórka musi mieć tyle samo schematów plików co emisja główna")

    source_day = latest_scheduled_premiere_day(show, day)
    if source_day is None:
        raise FileNotFoundError(
            "Nie znaleziono wcześniejszej zaplanowanej premiery. Spróbuj ręcznie wybrać pliki przez „Wybierz ręcznie”."
        )

    copies: list[tuple[dt.date, str, Path, str, Path]] = []
    for part_index in range(len(repeat_patterns)):
        target_relative, target = _path_for(repeat, day, media_root, part_index)
        if target.exists():
            continue
        source_relative, source_path = _path_for(show, source_day, media_root, part_index)
        if not source_path.is_file():
            raise FileNotFoundError(
                f"Brak pliku ostatniej zaplanowanej premiery z {source_day.isoformat()} — "
                f"część {part_index + 1}. Spróbuj ręcznie wybrać pliki przez „Wybierz ręcznie”."
            )
        copies.append((source_day, source_relative, source_path, target_relative, target))
    if not copies:
        raise FileExistsError("Wszystkie pliki powtórki już istnieją")
    try:
        for _, _, source_path, _, target in copies:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
    except OSError as exc:
        if exc.errno == errno.EROFS:
            message = (
                "Kontener widzi folder AUDYCJE jako tylko do odczytu. Samo „rw” w mouncie SMB nie wystarczy — "
                "w ustawieniach Storage aplikacji TrueNAS wyłącz Read Only dla /media/audycje."
            )
        elif exc.errno in {errno.EACCES, errno.EPERM}:
            message = "Brak prawa zapisu do folderu AUDYCJE. Nadaj użytkownikowi aplikacji (UID 568) prawo zapisu."
        else:
            message = f"Nie udało się utworzyć powtórki: {exc}"
        raise OSError(message) from exc
    first = copies[0]
    return {
        "created": True,
        "created_count": len(copies),
        "source_date": first[0].isoformat(),
        "source": first[1],
        "target": first[3],
        "files": [
            {"source_date": source_day.isoformat(), "source": source_relative, "target": target_relative}
            for source_day, source_relative, _, target_relative, _ in copies
        ],
    }


def create_substitute(
    show: dict[str, Any], day: dt.date, media_root: Path,
    source_paths: list[Any], repeat_id: str | None = None,
    archive_root: Path | None = None,
    source_roots: dict[str, Path] | None = None,
) -> dict[str, Any]:
    occurrence = show
    if repeat_id:
        occurrence = next((item for item in show.get("repeats", []) if item["id"] == repeat_id), None)
        if occurrence is None:
            raise ValueError("Nie znaleziono powtórki")
    targets = _patterns(occurrence)
    if len(source_paths) != len(targets):
        raise ValueError(f"Wybierz dokładnie {len(targets)} plik(i) źródłowe")
    copies: list[dict[str, str]] = []
    roots = {"media": media_root, "archive": archive_root}
    if source_roots:
        roots.update(source_roots)
    root_labels = {
        "media": "AUDYCJE",
        "archive": "Archiwum",
        "emaus": "Emaus",
        "emaus_contact": "Emaus Kontakt",
    }
    resolved: list[tuple[Path, str, Path, str, Path]] = []
    for index, raw_source in enumerate(source_paths):
        if isinstance(raw_source, dict):
            source_root_name = str(raw_source.get("root", "media")).strip().lower()
            source_relative = str(raw_source.get("path", "")).strip()
        else:
            source_root_name = "media"
            source_relative = str(raw_source or "").strip()
        source_root = roots.get(source_root_name)
        if source_root_name not in roots or source_root is None:
            raise ValueError("Nieznane źródło pliku powtórki")
        if not source_root.is_dir():
            raise FileNotFoundError("Wybrane źródło plików nie jest dostępne")
        source = safe_join(source_root, source_relative)
        if not source.is_file() or source.suffix.lower() not in AUDIO_SUFFIXES:
            root_label = root_labels.get(source_root_name, source_root_name)
            raise FileNotFoundError(f"Nie znaleziono pliku źródłowego: /{root_label}/{source_relative}")
        target_relative, target = _path_for(occurrence, day, media_root, index)
        resolved.append((source, target_relative, target, source_root_name, source_root))
    try:
        for source, target_relative, target, source_root_name, source_root in resolved:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.substitute.tmp")
            try:
                shutil.copy2(source, temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            copies.append({
                "source_root": source_root_name,
                "source": source.relative_to(source_root.resolve()).as_posix(),
                "target": target_relative,
            })
    except OSError as exc:
        raise OSError(f"Nie udało się utworzyć audycji zastępczej: {exc}") from exc
    return {"created": True, "copied": len(copies), "files": copies}


def build_author_archive(
    show: dict[str, Any], day: dt.date, media_root: Path, output_dir: Path,
) -> Path:
    if not show.get("send_to_author") or not show.get("author_email"):
        raise ValueError("Dla tej audycji nie włączono wysyłki do autora")
    item = check_occurrence(show, show, day, media_root)
    missing = [part for part in item["parts"] if not part["found"]]
    if missing:
        raise FileNotFoundError("Nie można przygotować paczki — brakuje co najmniej jednego pliku")
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(char if char.isalnum() or char in "-_" else "_" for char in show["name"]).strip("_")
    handle, archive_name = tempfile.mkstemp(
        prefix=f"{safe_name or 'audycja'}_{day.isoformat()}_", suffix=".zip", dir=output_dir
    )
    os.close(handle)
    archive = Path(archive_name)
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
            for part in item["parts"]:
                source = safe_join(media_root, part["relative_path"])
                bundle.write(source, arcname=source.name)
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    return archive
