from __future__ import annotations

import datetime as dt
import asyncio
import hashlib
import hmac
import json
import mimetypes
import os
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from fastapi import Cookie, FastAPI, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .auth import (
    SESSION_TTL_SECONDS,
    authenticate_pin,
    change_pin,
    initialize_auth,
    issue_session,
    validate_session,
)
from .checker import audio_duration, build_author_archive, build_report, create_substitute, generate_repeat
from .delivery import (
    disconnect_google_calendar,
    disconnect_google,
    drive_cleanup_loop,
    finish_google_calendar_flow,
    poll_google_device_flow,
    public_delivery_config,
    save_delivery_config,
    send_show_to_author,
    start_google_device_flow,
    start_google_calendar_flow,
    test_smtp,
)
from .db import database_from_env, normalize_author_emails
from .ftp_sync import (
    build_ftp_task_overview,
    browse_ftp_directories,
    ftp_source_status,
    ftp_sync_loop,
    mirror_ftp_show,
    rename_ftp_files,
)
from .google_calendar import GoogleCalendarClient
from .importer import import_legacy_xls, seed_if_empty
from .media_stream import file_chunks, parse_byte_range
from .maintenance import (
    archive_show_folder,
    archive_media_file_now,
    file_maintenance_loop,
    get_file_maintenance_settings,
    save_file_maintenance_settings,
    sync_show_pattern_templates,
)
from .patterns import infer_patterns, normalize_relative, preview_path, safe_join
from .notifications import (
    get_notification_settings,
    normalize_notification_settings,
    notification_loop,
    save_notification_settings,
    send_pushover,
)
from .spy import create_spy_clip, list_spy_files
from .timetable import seed_timetable_if_needed, sync_show_timetable_entry
from .zetta_played import (
    PlayedService,
    get_zetta_config,
    played_sync_loop,
    save_zetta_config,
)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", "/media/audycje"))
ARCHIVE_ROOT = Path(os.getenv("ARCHIVE_ROOT", "/media/archiwum"))
EMAUS_ROOT = Path(os.getenv("EMAUS_ROOT", "/media/emaus"))
EMAUS_CONTACT_ROOT = Path(os.getenv("EMAUS_CONTACT_ROOT", "/media/emaus-kontakt"))
SPY_ROOT = Path(os.getenv("SPY_ROOT", "/media/szpieg"))
EXPORT_ROOT = Path(os.getenv("EXPORT_ROOT", "/data/exports"))
DELIVERY_CONFIG_FILE = os.getenv("DELIVERY_CONFIG_FILE", "/data/delivery_config.json")
SEED_XLS = os.getenv("SEED_XLS", str(BASE_DIR.parent / "seed" / "audycje.xls"))
TIMETABLE_SEED = os.getenv(
    "TIMETABLE_SEED", str(BASE_DIR.parent / "seed" / "ramowka_jesien_2026.json")
)
SESSION_COOKIE = "sprawdzacz_edit_session"
SETTINGS_COOKIE = "sprawdzacz_settings_session"
SETTINGS_SESSION_TTL_SECONDS = 60 * 60
SETTINGS_PASSWORD = os.getenv("SETTINGS_PASSWORD", "RaEm^567!#")
TIMEZONE_NAME = os.getenv("TZ", "Europe/Warsaw")
FTP_CREDENTIALS_FILE = os.getenv("FTP_CREDENTIALS_FILE", "/data/forum_ftp_credentials")
if (
    FTP_CREDENTIALS_FILE == "/run/secrets/forum_ftp_credentials"
    and not Path(FTP_CREDENTIALS_FILE).is_file()
):
    # Bezpieczna migracja ze starej konfiguracji Custom App bez konieczności
    # natychmiastowego usuwania dawnej zmiennej środowiskowej.
    FTP_CREDENTIALS_FILE = "/data/forum_ftp_credentials"
APP_VERSION = "0.10.1"
ANDROID_APK_VERSION = APP_VERSION
ANDROID_APK_PATH = STATIC_DIR / "sprawdzacz-audycji.apk"
database = database_from_env()
played_service = PlayedService(database, TIMEZONE_NAME)
spy_downloads: dict[str, Path] = {}
browser_audio_cache: dict[str, tuple[int, int, int | None, str | None]] = {}
FILE_ROOTS = {
    "media": MEDIA_ROOT,
    "archive": ARCHIVE_ROOT,
    "emaus": EMAUS_ROOT,
    "emaus_contact": EMAUS_CONTACT_ROOT,
}
FILE_ROOT_LABELS = {
    "media": "AUDYCJE",
    "archive": "Archiwum",
    "emaus": "Emaus",
    "emaus_contact": "Emaus Kontakt",
}
FILE_FAVORITES_SETTING = "file_browser_favorites"
WINDOWS_PATHS_SETTING = "windows_path_mappings"
DEFAULT_WINDOWS_PATHS = {
    "media": r"\\83.emaus\dyna\dynamix\AUDYCJE",
    "archive": r"\\79.emaus\archiwum\ArchiwumEmausSWDM\AUDYCJE",
    "emaus": r"\\192.168.1.15\Emaus",
    "emaus_contact": r"\\192.168.1.15\Emaus Kontakt",
}


def _normalize_windows_path(value: Any) -> str:
    path = str(value or "").strip().rstrip("\\/")
    if not path:
        return ""
    if "\0" in path or "\n" in path or "\r" in path or not path.startswith("\\\\"):
        raise ValueError("Ścieżka Windows musi być ścieżką UNC zaczynającą się od \\\\")
    return path.replace("/", "\\")


def _windows_path_mappings() -> dict[str, str]:
    try:
        stored = json.loads(database.get_setting(WINDOWS_PATHS_SETTING, "{}") or "{}")
    except (TypeError, json.JSONDecodeError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    result: dict[str, str] = {}
    for root in FILE_ROOTS:
        try:
            result[root] = _normalize_windows_path(stored.get(root, DEFAULT_WINDOWS_PATHS[root]))
        except ValueError:
            result[root] = DEFAULT_WINDOWS_PATHS[root]
    return result


def _windows_path(
    root: str, relative: str, mappings: dict[str, str] | None = None
) -> str:
    base = (mappings or _windows_path_mappings()).get(root, "")
    if not base:
        return ""
    clean = normalize_relative(relative)
    return base if not clean else f"{base}\\{clean.replace('/', '\\')}"


def _file_favorites() -> list[dict[str, str]]:
    try:
        raw = json.loads(database.get_setting(FILE_FAVORITES_SETTING, "[]") or "[]")
    except (TypeError, json.JSONDecodeError):
        raw = []
    favorites: list[dict[str, str]] = []
    windows_mappings = _windows_path_mappings()
    seen: set[tuple[str, str]] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        root = str(item.get("root", "")).strip()
        try:
            path = normalize_relative(str(item.get("path", "")))
        except ValueError:
            continue
        key = (root, path)
        if root not in FILE_ROOTS or not path or key in seen:
            continue
        seen.add(key)
        favorites.append(
            {
                "root": root,
                "root_label": FILE_ROOT_LABELS[root],
                "path": path,
                "name": Path(path).name,
                "windows_path": _windows_path(root, path, windows_mappings),
            }
        )
    return sorted(
        favorites,
        key=lambda item: (item["name"].casefold(), item["root_label"].casefold(), item["path"].casefold()),
    )


def _iso_timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).isoformat()


def browser_audio_metadata(path: Path, file_stat: os.stat_result) -> tuple[int | None, str | None]:
    key = str(path.resolve())
    signature = (file_stat.st_mtime_ns, file_stat.st_size)
    cached = browser_audio_cache.get(key)
    if cached and cached[:2] == signature:
        return cached[2], cached[3]
    seconds, display = audio_duration(path)
    if len(browser_audio_cache) >= 5000:
        browser_audio_cache.clear()
    browser_audio_cache[key] = (*signature, seconds, display)
    return seconds, display


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    initialize_auth(database)
    seed_if_empty(database, SEED_XLS)
    seed_timetable_if_needed(database, TIMETABLE_SEED)
    database.apply_builtin_ftp_defaults_once()
    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    scheduler = asyncio.create_task(
        notification_loop(database, MEDIA_ROOT, TIMEZONE_NAME, FILE_ROOTS)
    )
    ftp_scheduler = asyncio.create_task(
        ftp_sync_loop(database, MEDIA_ROOT, FTP_CREDENTIALS_FILE, TIMEZONE_NAME)
    )
    drive_scheduler = asyncio.create_task(drive_cleanup_loop(database, DELIVERY_CONFIG_FILE))
    maintenance_scheduler = asyncio.create_task(
        file_maintenance_loop(database, MEDIA_ROOT, ARCHIVE_ROOT, FILE_ROOTS)
    )
    played_scheduler = asyncio.create_task(played_sync_loop(played_service))
    try:
        yield
    finally:
        scheduler.cancel()
        ftp_scheduler.cancel()
        drive_scheduler.cancel()
        maintenance_scheduler.cancel()
        played_scheduler.cancel()
        for task in (scheduler, ftp_scheduler, drive_scheduler, maintenance_scheduler, played_scheduler):
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Emaus Hub", version=APP_VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def require_edit(token: str | None) -> None:
    if not validate_session(database, token):
        raise HTTPException(status_code=401, detail="Edycja jest zablokowana")


def require_settings(token: str | None) -> None:
    if not validate_session(database, token, "settings"):
        raise HTTPException(status_code=401, detail="Ustawienia są zablokowane")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "shows": database.count_shows(),
        "media_root_available": MEDIA_ROOT.is_dir(),
        "archive_root_available": ARCHIVE_ROOT.is_dir(),
        "emaus_root_available": EMAUS_ROOT.is_dir(),
        "emaus_contact_root_available": EMAUS_CONTACT_ROOT.is_dir(),
        "spy_root_available": SPY_ROOT.is_dir(),
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "ftp_credentials_available": (
            Path(FTP_CREDENTIALS_FILE).is_file()
            and Path(FTP_CREDENTIALS_FILE).stat().st_size > 0
        ),
        "ftp_credentials_location": FTP_CREDENTIALS_FILE,
        "delivery_config_location": DELIVERY_CONFIG_FILE,
        "android_apk_available": ANDROID_APK_PATH.is_file(),
        "android_apk_version": ANDROID_APK_VERSION,
        "version": app.version,
    }


@app.get("/api/played")
def played_log(
    date: str = Query(default_factory=lambda: dt.date.today().isoformat()),
) -> dict[str, Any]:
    try:
        day = dt.date.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Nieprawidłowa data") from exc
    result = played_service.day(day)
    result.update({"date": day.isoformat(), "timezone": TIMEZONE_NAME})
    return result


@app.post("/api/played/refresh")
async def refresh_played_log(request: Request) -> dict[str, Any]:
    body = await request.json()
    try:
        day = dt.date.fromisoformat(str(body.get("date") or dt.date.today().isoformat()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Nieprawidłowa data") from exc
    try:
        if bool(body.get("full", False)):
            sync = await asyncio.to_thread(played_service.refresh_day, day)
        else:
            now = dt.datetime.now(ZoneInfo(TIMEZONE_NAME))
            hours = [now.hour - 1, now.hour, now.hour + 1] if day == now.date() else list(range(24))
            sync = await asyncio.to_thread(played_service.refresh_hours, day, hours)
        return {"sync": sync, **played_service.day(day), "date": day.isoformat(), "timezone": TIMEZONE_NAME}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (requests.RequestException, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def version_key(value: str) -> tuple[int, ...]:
    numbers = tuple(int(part) for part in re.findall(r"\d+", value))
    return numbers or (0,)


@app.get("/api/android/update")
def android_update(current: str = Query(default="0")) -> dict[str, Any]:
    available = ANDROID_APK_PATH.is_file()
    digest = None
    if available:
        with ANDROID_APK_PATH.open("rb") as apk_file:
            digest = hashlib.file_digest(apk_file, "sha256").hexdigest()
    return {
        "current_version": current,
        "latest_version": ANDROID_APK_VERSION,
        "update_available": available and version_key(ANDROID_APK_VERSION) > version_key(current),
        "apk_available": available,
        "apk_url": "/api/android/apk" if available else None,
        "sha256": digest,
    }


@app.get("/api/android/apk")
def android_apk() -> FileResponse:
    if not ANDROID_APK_PATH.is_file():
        raise HTTPException(status_code=404, detail="Pakiet aktualizacji Android nie jest dostępny")
    return FileResponse(
        ANDROID_APK_PATH,
        filename=f"emaus-hub-{ANDROID_APK_VERSION}.apk",
        media_type="application/vnd.android.package-archive",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/auth/status")
def auth_status(sprawdzacz_edit_session: str | None = Cookie(default=None)) -> dict[str, bool]:
    return {"unlocked": validate_session(database, sprawdzacz_edit_session)}


@app.post("/api/auth/unlock")
async def unlock(request: Request, response: Response) -> dict[str, bool]:
    body = await request.json()
    if not authenticate_pin(database, str(body.get("pin", ""))):
        raise HTTPException(status_code=401, detail="Nieprawidłowy PIN")
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(database),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
    )
    return {"unlocked": True}


@app.post("/api/auth/lock")
def lock(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE)
    return {"unlocked": False}


@app.post("/api/auth/change-pin")
async def update_pin(
    request: Request, sprawdzacz_settings_session: str | None = Cookie(default=None)
) -> dict[str, bool]:
    require_settings(sprawdzacz_settings_session)
    body = await request.json()
    try:
        change_pin(database, str(body.get("new_pin", "")))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/api/settings/status")
def settings_status(
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, bool]:
    return {"unlocked": validate_session(database, sprawdzacz_settings_session, "settings")}


@app.post("/api/settings/unlock")
async def unlock_settings(request: Request, response: Response) -> dict[str, bool]:
    body = await request.json()
    candidate = str(body.get("password", ""))
    if not hmac.compare_digest(candidate.encode("utf-8"), SETTINGS_PASSWORD.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Nieprawidłowe hasło ustawień")
    response.set_cookie(
        SETTINGS_COOKIE,
        issue_session(database, "settings", SETTINGS_SESSION_TTL_SECONDS),
        max_age=SETTINGS_SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
    )
    return {"unlocked": True}


@app.post("/api/settings/lock")
def lock_settings(response: Response) -> dict[str, bool]:
    response.delete_cookie(SETTINGS_COOKIE)
    return {"unlocked": False}


@app.get("/api/settings/notifications")
def notification_settings(
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    return get_notification_settings(database)


@app.put("/api/settings/notifications")
async def update_notification_settings(
    request: Request,
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    try:
        return save_notification_settings(database, await request.json())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/settings/file-maintenance")
def file_maintenance_settings(
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, int]:
    require_settings(sprawdzacz_settings_session)
    return get_file_maintenance_settings(database)


@app.put("/api/settings/file-maintenance")
async def update_file_maintenance_settings(
    request: Request,
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, int]:
    require_settings(sprawdzacz_settings_session)
    try:
        return save_file_maintenance_settings(database, await request.json())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/settings/windows-paths")
def windows_path_settings(
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    return {
        "mappings": _windows_path_mappings(),
    }


@app.put("/api/settings/windows-paths")
async def update_windows_path_settings(
    request: Request,
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    body = await request.json()
    mappings = body.get("mappings", body)
    if not isinstance(mappings, dict):
        raise HTTPException(status_code=422, detail="Nieprawidłowa konfiguracja ścieżek Windows")
    try:
        normalized = {
            root: _normalize_windows_path(mappings.get(root, ""))
            for root in FILE_ROOTS
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    database.set_setting(WINDOWS_PATHS_SETTING, json.dumps(normalized, ensure_ascii=False))
    return {
        "mappings": normalized,
    }


@app.get("/api/settings/zetta")
def zetta_settings(
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    return get_zetta_config(database)


@app.put("/api/settings/zetta")
async def update_zetta_settings(
    request: Request,
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    try:
        return save_zetta_config(database, await request.json())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/settings/zetta/test")
async def test_zetta_connection(
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    try:
        return await asyncio.to_thread(played_service.test_connection)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (requests.RequestException, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/settings/pushover/test")
async def test_pushover(
    request: Request,
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, bool]:
    require_settings(sprawdzacz_settings_session)
    normalized = normalize_notification_settings({"recipients": [await request.json()]})
    if not normalized["recipients"]:
        raise HTTPException(status_code=422, detail="Brak danych odbiorcy")
    recipient = normalized["recipients"][0]
    if not recipient["app_token"] or not recipient["user_key"]:
        raise HTTPException(status_code=422, detail="Podaj API Token i User/Group Key")
    try:
        await asyncio.to_thread(
            send_pushover,
            recipient,
            "Test — Emaus Hub",
            "Połączenie z Pushover działa poprawnie.",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"sent": True}


@app.get("/api/settings/delivery")
def delivery_settings(
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    return public_delivery_config(DELIVERY_CONFIG_FILE)


@app.put("/api/settings/delivery")
async def update_delivery_settings(
    request: Request,
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    try:
        return save_delivery_config(DELIVERY_CONFIG_FILE, await request.json())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/settings/delivery/google/start")
async def start_google_connection(
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    try:
        return await asyncio.to_thread(start_google_device_flow, DELIVERY_CONFIG_FILE)
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/settings/delivery/google/poll")
async def poll_google_connection(
    request: Request,
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    body = await request.json()
    try:
        return await asyncio.to_thread(poll_google_device_flow, str(body.get("flow_id", "")))
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/settings/delivery/google/disconnect")
async def disconnect_google_connection(
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, bool]:
    require_settings(sprawdzacz_settings_session)
    await asyncio.to_thread(disconnect_google, DELIVERY_CONFIG_FILE)
    return {"disconnected": True}


@app.post("/api/settings/delivery/calendar/start")
async def start_calendar_connection(
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    try:
        return await asyncio.to_thread(start_google_calendar_flow, DELIVERY_CONFIG_FILE)
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/settings/delivery/calendar/finish")
async def finish_calendar_connection(
    request: Request,
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    body = await request.json()
    try:
        return await asyncio.to_thread(
            finish_google_calendar_flow,
            DELIVERY_CONFIG_FILE,
            str(body.get("state", "")),
            str(body.get("returned_value", "")),
        )
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/settings/delivery/calendar/disconnect")
async def disconnect_calendar_connection(
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, bool]:
    require_settings(sprawdzacz_settings_session)
    await asyncio.to_thread(disconnect_google_calendar, DELIVERY_CONFIG_FILE)
    return {"disconnected": True}


@app.get("/api/settings/delivery/calendars")
async def google_calendar_choices(
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_settings(sprawdzacz_settings_session)
    try:
        client = await asyncio.to_thread(GoogleCalendarClient, DELIVERY_CONFIG_FILE)
        calendars = await asyncio.to_thread(client.list_calendars)
        return {"calendars": calendars}
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/settings/delivery/smtp/test")
async def test_delivery_smtp(
    sprawdzacz_settings_session: str | None = Cookie(default=None),
) -> dict[str, bool]:
    require_settings(sprawdzacz_settings_session)
    try:
        await asyncio.to_thread(test_smtp, DELIVERY_CONFIG_FILE)
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"sent": True}


@app.get("/api/calendar/events")
async def calendar_events(start: str, end: str) -> dict[str, Any]:
    config = public_delivery_config(DELIVERY_CONFIG_FILE)
    base = {
        "connected": bool(config["google_connected"]),
        "calendar_access": bool(config["google_calendar_access"]),
        "configured": bool(config["calendar_configured"]),
        "calendar_name": str(config.get("calendar_name") or ""),
        "writable": str(config.get("calendar_access_role") or "")
        in {"owner", "writer", "writerWithoutPrivateAccess"},
    }
    if not base["connected"] or not base["calendar_access"] or not base["configured"]:
        return {**base, "events": []}
    try:
        start_date = dt.date.fromisoformat(start)
        end_date = dt.date.fromisoformat(end)
        if end_date <= start_date:
            raise ValueError("Koniec zakresu musi być później niż początek")
        if (end_date - start_date).days > 45:
            raise ValueError("Zakres Grafiku nie może przekraczać 45 dni")
        timezone = ZoneInfo(TIMEZONE_NAME)
        time_min = dt.datetime.combine(start_date, dt.time.min, timezone).isoformat()
        time_max = dt.datetime.combine(end_date, dt.time.min, timezone).isoformat()
        client = await asyncio.to_thread(GoogleCalendarClient, DELIVERY_CONFIG_FILE)
        events = await asyncio.to_thread(client.list_events, time_min, time_max, TIMEZONE_NAME)
        return {**base, "events": events}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/calendar/events")
async def create_calendar_event(
    request: Request, sprawdzacz_edit_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    try:
        client = await asyncio.to_thread(GoogleCalendarClient, DELIVERY_CONFIG_FILE)
        event = await asyncio.to_thread(
            client.create_event, await request.json(), TIMEZONE_NAME
        )
        return {"event": event}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.patch("/api/calendar/events/{event_id}")
async def update_calendar_event(
    event_id: str,
    request: Request,
    sprawdzacz_edit_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    try:
        client = await asyncio.to_thread(GoogleCalendarClient, DELIVERY_CONFIG_FILE)
        event = await asyncio.to_thread(
            client.update_event, event_id, await request.json(), TIMEZONE_NAME
        )
        return {"event": event}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.delete("/api/calendar/events/{event_id}")
async def delete_calendar_event(
    event_id: str,
    sprawdzacz_edit_session: str | None = Cookie(default=None),
) -> dict[str, bool]:
    require_edit(sprawdzacz_edit_session)
    try:
        client = await asyncio.to_thread(GoogleCalendarClient, DELIVERY_CONFIG_FILE)
        await asyncio.to_thread(client.delete_event, event_id)
        return {"deleted": True}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/report")
def report(date: str = Query(default_factory=lambda: dt.date.today().isoformat())) -> dict[str, Any]:
    try:
        day = dt.date.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Nieprawidłowa data") from exc
    result = build_report(database.list_shows(include_inactive=False), day, MEDIA_ROOT)
    ignored = database.ignored_report_occurrences(day.isoformat())
    deliveries = database.successful_author_deliveries(day.isoformat())
    for item in result["items"]:
        item["ignored"] = (
            not item["found"]
            and (int(item["id"]), str(item["occurrence_key"])) in ignored
        )
        try:
            author_emails = normalize_author_emails(item.get("author_email", ""))
        except ValueError:
            author_emails = []
        author_deliveries = (
            [
                deliveries.get((int(item["id"]), recipient.casefold()))
                for recipient in author_emails
            ]
            if item.get("occurrence_type") == "main"
            else []
        )
        completed_deliveries = [delivery for delivery in author_deliveries if delivery]
        item["author_emails"] = author_emails
        item["author_sent"] = bool(author_emails) and len(completed_deliveries) == len(author_emails)
        item["author_deliveries"] = completed_deliveries
        item["author_delivery"] = (
            max(completed_deliveries, key=lambda delivery: str(delivery.get("sent_at", "")))
            if item["author_sent"]
            else None
        )
    result["found"] = sum(1 for item in result["items"] if item["found"] or item["ignored"])
    result["missing"] = result["total"] - result["found"]
    return result


@app.post("/api/report/ignore")
async def ignore_report_occurrence(
    request: Request, sprawdzacz_edit_session: str | None = Cookie(default=None)
) -> dict[str, bool]:
    require_edit(sprawdzacz_edit_session)
    body = await request.json()
    try:
        show_id = int(body.get("show_id"))
        day = dt.date.fromisoformat(str(body.get("date", "")))
        occurrence_key = str(body.get("occurrence_key", "")).strip()
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Nieprawidłowe dane audycji") from exc
    if not occurrence_key:
        raise HTTPException(status_code=422, detail="Brak identyfikatora emisji")
    current = build_report(database.list_shows(include_inactive=False), day, MEDIA_ROOT)
    item = next(
        (
            candidate for candidate in current["items"]
            if int(candidate["id"]) == show_id
            and str(candidate.get("occurrence_key", "")) == occurrence_key
        ),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono tej emisji w wybranym dniu")
    if item["found"]:
        raise HTTPException(status_code=409, detail="Audycja jest już kompletna")
    database.ignore_report_occurrence(show_id, occurrence_key, day.isoformat())
    return {"ignored": True}


@app.post("/api/report/generate-repeat")
async def create_repeat_file(
    request: Request, sprawdzacz_edit_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    body = await request.json()
    try:
        show_id = int(body.get("show_id"))
        repeat_id = str(body.get("repeat_id", ""))
        day = dt.date.fromisoformat(str(body.get("date", "")))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Nieprawidłowe dane powtórki") from exc
    show = database.get_show(show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono audycji")
    try:
        return generate_repeat(show, repeat_id, day, MEDIA_ROOT)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/report/substitute")
async def substitute_file(
    request: Request, sprawdzacz_edit_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    body = await request.json()
    try:
        show_id = int(body.get("show_id"))
        day = dt.date.fromisoformat(str(body.get("date", "")))
        raw_sources = body.get("source_files", body.get("source_paths", []))
        if not isinstance(raw_sources, list):
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Nieprawidłowe dane audycji zastępczej") from exc
    show = database.get_show(show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono audycji")
    try:
        result = await asyncio.to_thread(
            create_substitute, show, day, MEDIA_ROOT, raw_sources,
            str(body.get("repeat_id") or "") or None, ARCHIVE_ROOT, FILE_ROOTS,
        )
        observed_at = dt.datetime.now(dt.timezone.utc).isoformat()
        for item in result.get("files", []):
            if item.get("source_root") != "archive":
                continue
            target = safe_join(MEDIA_ROOT, str(item.get("target", "")))
            file_stat = target.stat()
            database.observe_maintenance_file(
                "archive",
                show_id,
                "",
                str(item.get("target", "")),
                file_stat.st_size,
                file_stat.st_mtime_ns,
                observed_at,
                "archive_restore",
            )
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Brak prawa zapisu do folderu audycji") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/report/author-package")
async def author_package(
    show_id: int,
    date: str,
    sprawdzacz_edit_session: str | None = Cookie(default=None),
) -> FileResponse:
    require_edit(sprawdzacz_edit_session)
    try:
        day = dt.date.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Nieprawidłowa data") from exc
    show = database.get_show(show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono audycji")
    try:
        archive = await asyncio.to_thread(
            build_author_archive, show, day, MEDIA_ROOT, Path(os.getenv("EXPORT_ROOT", "/data/exports"))
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(
        archive,
        filename=f"{show['name']}_{day.isoformat()}.zip",
        media_type="application/zip",
        background=BackgroundTask(archive.unlink, missing_ok=True),
    )


@app.post("/api/report/send-author")
async def deliver_show_to_author(
    request: Request, sprawdzacz_edit_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    body = await request.json()
    try:
        show_id = int(body.get("show_id"))
        day = dt.date.fromisoformat(str(body.get("date", "")))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Nieprawidłowe dane wysyłki") from exc
    show = database.get_show(show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono audycji")
    try:
        return await asyncio.to_thread(
            send_show_to_author, database, show, day, MEDIA_ROOT, DELIVERY_CONFIG_FILE
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/ftp/directories")
async def ftp_directories(
    path: str = "/",
    sprawdzacz_edit_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    try:
        return await asyncio.to_thread(browse_ftp_directories, path, FTP_CREDENTIALS_FILE)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/ftp/status")
def ftp_status(show_id: int, date: str) -> dict[str, Any]:
    try:
        day = dt.date.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Nieprawidłowa data") from exc
    show = database.get_show(show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono audycji")
    try:
        sources = ftp_source_status(show, show, day, MEDIA_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "source_path": show.get("ftp_source_path", ""),
        "destination": show.get("folder_pattern", ""),
        "sources": sources,
        "can_rename": bool(sources) and all(item["found"] for item in sources),
        "renamed": bool(sources) and all(item.get("renamed") for item in sources),
    }


@app.get("/api/ftp/tasks")
def ftp_tasks() -> dict[str, Any]:
    result = build_ftp_task_overview(database, TIMEZONE_NAME)
    credentials_path = Path(FTP_CREDENTIALS_FILE)
    result["credentials_available"] = (
        credentials_path.is_file() and credentials_path.stat().st_size > 0
    )
    return result


@app.post("/api/ftp/sync")
async def sync_ftp_show(
    request: Request,
    sprawdzacz_edit_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    body = await request.json()
    try:
        show_id = int(body.get("show_id"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Nieprawidłowa audycja") from exc
    show = database.get_show(show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono audycji")
    if "ftp_source_path" in body or "folder_pattern" in body:
        require_edit(sprawdzacz_edit_session)
        show = {
            **show,
            "is_ftp": True,
            "ftp_source_path": str(body.get("ftp_source_path", show.get("ftp_source_path", ""))).strip(),
            "folder_pattern": str(body.get("folder_pattern", show.get("folder_pattern", ""))).strip(),
        }
    try:
        result = await asyncio.to_thread(mirror_ftp_show, show, MEDIA_ROOT, FTP_CREDENTIALS_FILE)
    except PermissionError as exc:
        database.record_manual_ftp_sync(show_id, "failed", str(exc))
        raise HTTPException(status_code=403, detail="Brak prawa zapisu do folderu audycji") from exc
    except (ValueError, RuntimeError, OSError) as exc:
        database.record_manual_ftp_sync(show_id, "failed", str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    database.record_manual_ftp_sync(show_id, "synced", result.get("detail", ""))
    return result


@app.post("/api/ftp/rename")
async def rename_ftp_show_files(request: Request) -> dict[str, Any]:
    body = await request.json()
    try:
        show_id = int(body.get("show_id"))
        day = dt.date.fromisoformat(str(body.get("date", "")))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Nieprawidłowe dane audycji") from exc
    show = database.get_show(show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono audycji")
    try:
        return await asyncio.to_thread(
            rename_ftp_files,
            show,
            day,
            MEDIA_ROOT,
            str(body.get("repeat_id") or "") or None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Brak prawa zapisu do folderu audycji") from exc
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/shows")
def shows() -> dict[str, Any]:
    return {"items": database.list_shows(include_inactive=True), "import": database.latest_import()}


@app.get("/api/timetable")
def timetable() -> dict[str, Any]:
    result = database.timetable()
    result["shows"] = database.list_shows(include_inactive=True)
    return result


@app.post("/api/timetable/entries")
async def create_timetable_entry(
    request: Request, sprawdzacz_edit_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    try:
        body = await request.json()
        if body.get("show_id") not in (None, ""):
            item = sync_show_timetable_entry(database, None, body)
            if item is None:
                raise ValueError("Nie udało się dodać emisji audycji")
            return item
        return database.create_timetable_entry(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/timetable/entries/bulk")
async def update_timetable_entries(
    request: Request,
    sprawdzacz_edit_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    try:
        body = await request.json()
        updates = body.get("updates", []) if isinstance(body, dict) else []
        if not isinstance(updates, list):
            raise ValueError("Nieprawidłowa lista emisji")
        items = database.update_timetable_entries(updates)
        return {"items": items, "updated": len(items)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/timetable/entries/{entry_id}")
async def update_timetable_entry(
    entry_id: int,
    request: Request,
    sprawdzacz_edit_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    try:
        before = database.get_timetable_entry(entry_id)
        if before is None:
            raise HTTPException(status_code=404, detail="Nie znaleziono elementu ramówki")
        body = await request.json()
        before_is_show = before.get("show_id") is not None
        after_is_show = body.get("show_id") not in (None, "")
        if before_is_show or after_is_show:
            if before_is_show and after_is_show:
                item = sync_show_timetable_entry(database, before, body)
            elif before_is_show:
                sync_show_timetable_entry(database, before, None)
                item = database.create_timetable_entry(body)
            else:
                database.delete_timetable_entry(entry_id)
                item = sync_show_timetable_entry(database, None, body)
        else:
            item = database.update_timetable_entry(entry_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono elementu ramówki")
    return item


@app.delete("/api/timetable/entries/{entry_id}")
def delete_timetable_entry(
    entry_id: int, sprawdzacz_edit_session: str | None = Cookie(default=None)
) -> dict[str, bool]:
    require_edit(sprawdzacz_edit_session)
    before = database.get_timetable_entry(entry_id)
    if before is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono elementu ramówki")
    try:
        if before.get("show_id") is not None:
            sync_show_timetable_entry(database, before, None)
        elif not database.delete_timetable_entry(entry_id):
            raise HTTPException(status_code=404, detail="Nie znaleziono elementu ramówki")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"deleted": True}


@app.post("/api/shows")
async def create_show(
    request: Request, sprawdzacz_edit_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    try:
        item = database.create_show(await request.json())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        item["pattern_templates"] = await asyncio.to_thread(
            sync_show_pattern_templates, MEDIA_ROOT, item
        )
    except (OSError, ValueError) as exc:
        item["pattern_template_warning"] = (
            "Audycję zapisano, ale nie udało się utworzyć pliku .wzor: "
            f"{exc}"
        )
    return item


@app.put("/api/shows/{show_id}")
async def update_show(
    show_id: int,
    request: Request,
    sprawdzacz_edit_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    previous = database.get_show(show_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono audycji")
    try:
        item = database.update_show(show_id, await request.json())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono audycji")
    try:
        item["pattern_templates"] = await asyncio.to_thread(
            sync_show_pattern_templates, MEDIA_ROOT, item, previous
        )
    except (OSError, ValueError) as exc:
        item["pattern_template_warning"] = (
            "Zmiany zapisano, ale nie udało się zaktualizować pliku .wzor: "
            f"{exc}"
        )
    return item


@app.delete("/api/shows/{show_id}")
async def delete_show(
    show_id: int, sprawdzacz_edit_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    show = database.get_show(show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono audycji")
    try:
        archive_result = await asyncio.to_thread(
            archive_show_folder, database, MEDIA_ROOT, ARCHIVE_ROOT, show
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail="Brak prawa zapisu do Archiwum lub usunięcia folderu z AUDYCJE",
        ) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not database.delete_show(show_id):
        raise HTTPException(status_code=404, detail="Nie znaleziono audycji")
    return {
        "deleted": True,
        "archive": archive_result,
        "ftp_disabled": bool(show.get("is_ftp")),
    }


@app.get("/api/audio")
def stream_audio(request: Request, path: str, root: str = "media") -> StreamingResponse:
    roots = {**FILE_ROOTS, "spy": SPY_ROOT}
    selected_root = roots.get(root)
    if selected_root is None:
        raise HTTPException(status_code=400, detail="Nieznane źródło audio")
    try:
        source = safe_join(selected_root, normalize_relative(path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Plik audio nie istnieje")
    if source.suffix.lower() not in {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}:
        raise HTTPException(status_code=415, detail="To nie jest obsługiwany plik audio")
    size = source.stat().st_size
    if size <= 0:
        raise HTTPException(status_code=422, detail="Plik audio jest pusty")
    media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    try:
        requested_range = parse_byte_range(request.headers.get("range"), size)
    except ValueError as exc:
        raise HTTPException(
            status_code=416,
            detail=str(exc),
            headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
        ) from exc
    start, end = requested_range or (0, size - 1)
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
        "Content-Length": str(end - start + 1),
    }
    status_code = 200
    if requested_range is not None:
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        file_chunks(source, start, end),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )


@app.get("/api/spy")
def spy_files(date: str = Query(default_factory=lambda: dt.date.today().isoformat())) -> dict[str, Any]:
    try:
        day = dt.date.fromisoformat(date)
        items = list_spy_files(SPY_ROOT, day)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Nieprawidłowa data") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"date": day.isoformat(), "items": items, "count": len(items), "max_clip_minutes": 180}


@app.post("/api/spy/cut")
async def cut_spy_audio(request: Request) -> dict[str, str]:
    body = await request.json()
    try:
        day = dt.date.fromisoformat(str(body.get("date", "")))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Nieprawidłowa data") from exc
    try:
        output = await asyncio.to_thread(
            create_spy_clip,
            SPY_ROOT,
            day,
            str(body.get("start_time", "")),
            str(body.get("end_time", "")),
            EXPORT_ROOT,
            str(body.get("filename", "")),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    token = uuid.uuid4().hex
    spy_downloads[token] = output
    filename = output.name.split("_", 1)[1] if "_" in output.name else output.name
    return {"filename": filename, "download_url": f"/api/spy/download/{token}"}


@app.get("/api/spy/download/{token}")
def download_spy_audio(token: str) -> FileResponse:
    source = spy_downloads.pop(token, None)
    if source is None or not source.is_file():
        raise HTTPException(status_code=404, detail="Plik wygasł — przygotuj wycinek ponownie")
    filename = source.name.split("_", 1)[1] if "_" in source.name else source.name
    return FileResponse(
        source,
        filename=filename,
        media_type="audio/mpeg",
        background=BackgroundTask(source.unlink, missing_ok=True),
    )


@app.get("/api/files")
def browse_files(path: str = "", root: str = "media", sort: str = "name") -> dict[str, Any]:
    selected_root = FILE_ROOTS.get(root)
    if selected_root is None:
        raise HTTPException(status_code=400, detail="Nieznane źródło plików")
    if not selected_root.is_dir():
        label = FILE_ROOT_LABELS.get(root, root)
        raise HTTPException(status_code=404, detail=f"Źródło {label} nie jest dostępne")
    try:
        relative = normalize_relative(path)
        directory = safe_join(selected_root, relative)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail="Folder nie istnieje")
    if sort not in {"name", "newest", "oldest"}:
        raise HTTPException(status_code=400, detail="Nieznany sposób sortowania")
    entries = []
    windows_mappings = _windows_path_mappings()
    try:
        children = list(directory.iterdir())
    except OSError as exc:
        raise HTTPException(status_code=403, detail=f"Brak dostępu do folderu: {exc}") from exc
    for child in children:
        if child.name.startswith("."):
            continue
        child_relative = child.relative_to(selected_root.resolve()).as_posix()
        audio = child.suffix.lower() in {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}
        try:
            child_stat = child.stat()
            modified_timestamp = child_stat.st_mtime
            modified_at = dt.datetime.fromtimestamp(modified_timestamp, tz=dt.timezone.utc).isoformat()
        except OSError:
            modified_timestamp = 0.0
            modified_at = None
        entries.append(
            {
                "name": child.name,
                "path": child_relative,
                "type": "directory" if child.is_dir() else "file",
                "audio": audio,
                "modified_at": modified_at,
                "windows_path": _windows_path(root, child_relative, windows_mappings),
                "_modified_timestamp": modified_timestamp,
            }
        )
    if sort == "newest":
        entries.sort(key=lambda item: (item["type"] != "directory", -item["_modified_timestamp"], item["name"].casefold()))
    elif sort == "oldest":
        entries.sort(key=lambda item: (item["type"] != "directory", item["_modified_timestamp"], item["name"].casefold()))
    else:
        entries.sort(key=lambda item: (item["type"] != "directory", item["name"].casefold()))
    entries = entries[:1000]
    for entry in entries:
        entry.pop("_modified_timestamp", None)
    parent = None if not relative else str(Path(relative).parent).replace("\\", "/")
    if parent == ".":
        parent = ""
    return {
        "root": root,
        "path": relative,
        "parent": parent,
        "sort": sort,
        "windows_path": _windows_path(root, relative, windows_mappings),
        "entries": entries,
    }


@app.get("/api/files/windows-paths")
def public_windows_path_settings() -> dict[str, Any]:
    return {"mappings": _windows_path_mappings()}


@app.get("/api/files/windows-path")
def file_windows_path(path: str = "", root: str = "media") -> dict[str, Any]:
    selected_root = FILE_ROOTS.get(root)
    if selected_root is None:
        raise HTTPException(status_code=400, detail="Nieznane źródło plików")
    try:
        relative = normalize_relative(path)
        source = safe_join(selected_root, relative)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not source.exists() or source.is_symlink():
        raise HTTPException(status_code=404, detail="Plik lub folder nie istnieje")
    windows_path = _windows_path(root, relative)
    if not windows_path:
        raise HTTPException(status_code=422, detail="Nie skonfigurowano ścieżki Windows dla tego źródła")
    return {
        "root": root,
        "path": relative,
        "windows_path": windows_path,
        "type": "directory" if source.is_dir() else "file",
    }


@app.get("/api/files/download")
def download_browser_file(path: str, root: str = "media") -> FileResponse:
    selected_root = FILE_ROOTS.get(root)
    if selected_root is None:
        raise HTTPException(status_code=400, detail="Nieznane źródło plików")
    try:
        relative = normalize_relative(path)
        source = safe_join(selected_root, relative)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not source.is_file() or source.is_symlink():
        raise HTTPException(status_code=404, detail="Plik nie istnieje")
    return FileResponse(
        source,
        filename=source.name,
        media_type=mimetypes.guess_type(source.name)[0] or "application/octet-stream",
    )


@app.get("/api/files/favorites")
def file_favorites() -> dict[str, Any]:
    return {"items": _file_favorites()}


@app.post("/api/files/favorites/toggle")
async def toggle_file_favorite(request: Request) -> dict[str, Any]:
    body = await request.json()
    root = str(body.get("root", "")).strip()
    selected_root = FILE_ROOTS.get(root)
    if selected_root is None:
        raise HTTPException(status_code=400, detail="Nieznane źródło plików")
    try:
        relative = normalize_relative(str(body.get("path", "")))
        directory = safe_join(selected_root, relative)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not relative or not directory.is_dir() or directory.is_symlink():
        raise HTTPException(status_code=404, detail="Folder nie istnieje")
    current = _file_favorites()
    key = (root, relative)
    stored = [{"root": item["root"], "path": item["path"]} for item in current]
    removed = any((item["root"], item["path"]) == key for item in current)
    if removed:
        stored = [item for item in stored if (item["root"], item["path"]) != key]
    else:
        stored.append({"root": root, "path": relative})
    database.set_setting(FILE_FAVORITES_SETTING, json.dumps(stored, ensure_ascii=False))
    return {"favorite": not removed, "items": _file_favorites()}


@app.get("/api/files/properties")
def file_properties(path: str, root: str = "media") -> dict[str, Any]:
    selected_root = FILE_ROOTS.get(root)
    if selected_root is None:
        raise HTTPException(status_code=400, detail="Nieznane źródło plików")
    try:
        relative = normalize_relative(path)
        source = safe_join(selected_root, relative)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not source.exists() or source.is_symlink():
        raise HTTPException(status_code=404, detail="Plik lub folder nie istnieje")
    try:
        file_stat = source.stat()
    except OSError as exc:
        raise HTTPException(status_code=403, detail=f"Nie udało się odczytać właściwości: {exc}") from exc
    is_directory = source.is_dir()
    result: dict[str, Any] = {
        "root": root,
        "root_label": FILE_ROOT_LABELS[root],
        "path": relative,
        "name": source.name,
        "type": "directory" if is_directory else "file",
        "extension": "" if is_directory else source.suffix,
        "size": None if is_directory else file_stat.st_size,
        "modified_at": _iso_timestamp(file_stat.st_mtime),
        "accessed_at": _iso_timestamp(file_stat.st_atime),
        "changed_at": _iso_timestamp(file_stat.st_ctime),
        "created_at": _iso_timestamp(getattr(file_stat, "st_birthtime", None)),
        "mime_type": None if is_directory else mimetypes.guess_type(source.name)[0],
        "duration_seconds": None,
        "duration": None,
        "bitrate_kbps": None,
        "sample_rate_hz": None,
        "channels": None,
        "codec": None,
    }
    if not is_directory and source.suffix.lower() in {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}:
        seconds, display = browser_audio_metadata(source, file_stat)
        result["duration_seconds"] = seconds
        result["duration"] = display
        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(source)
            info = getattr(audio, "info", None) if audio is not None else None
            result["bitrate_kbps"] = (
                round(float(info.bitrate) / 1000) if getattr(info, "bitrate", None) else None
            )
            result["sample_rate_hz"] = getattr(info, "sample_rate", None)
            result["channels"] = getattr(info, "channels", None)
            mime = getattr(audio, "mime", None) if audio is not None else None
            result["codec"] = mime[0] if isinstance(mime, list) and mime else result["mime_type"]
        except Exception:
            pass
    return result


@app.post("/api/files/rename")
async def rename_file(
    request: Request, sprawdzacz_edit_session: str | None = Cookie(default=None)
) -> dict[str, str]:
    require_edit(sprawdzacz_edit_session)
    body = await request.json()
    root = str(body.get("root", "")).strip()
    selected_root = FILE_ROOTS.get(root)
    if selected_root is None:
        raise HTTPException(status_code=400, detail="Nieznane źródło plików")
    name = str(body.get("name", "")).strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\0" in name:
        raise HTTPException(status_code=422, detail="Podaj poprawną nazwę pliku")
    try:
        relative = normalize_relative(str(body.get("path", "")))
        source = safe_join(selected_root, relative)
        parent = str(Path(relative).parent).replace("\\", "/")
        if parent == ".":
            parent = ""
        target_relative = normalize_relative(f"{parent}/{name}" if parent else name)
        target = safe_join(selected_root, target_relative)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not source.is_file() or source.is_symlink():
        raise HTTPException(status_code=404, detail="Plik nie istnieje")
    if target == source:
        return {"root": root, "path": relative, "name": source.name}
    if target.exists():
        raise HTTPException(status_code=409, detail="Plik o tej nazwie już istnieje")
    cache_key = str(source.resolve())
    try:
        source.rename(target)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Brak uprawnień do zmiany nazwy pliku") from exc
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"Nie udało się zmienić nazwy: {exc}") from exc
    browser_audio_cache.pop(cache_key, None)
    return {"root": root, "path": target_relative, "name": name}


@app.post("/api/files/archive-now")
async def archive_file_now(
    request: Request, sprawdzacz_edit_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    body = await request.json()
    if str(body.get("root", "media")).strip() != "media":
        raise HTTPException(
            status_code=422,
            detail="Ręcznie archiwizować można tylko pliki z AUDYCJE",
        )
    try:
        return await asyncio.to_thread(
            archive_media_file_now,
            database,
            MEDIA_ROOT,
            ARCHIVE_ROOT,
            str(body.get("path", "")),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail="Brak prawa zapisu do Archiwum lub usunięcia pliku z AUDYCJE",
        ) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/files/metadata")
def file_metadata(path: str, root: str = "media") -> dict[str, Any]:
    selected_root = FILE_ROOTS.get(root)
    if selected_root is None:
        raise HTTPException(status_code=400, detail="Nieznane źródło plików")
    if not selected_root.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Źródło {FILE_ROOT_LABELS.get(root, root)} nie jest dostępne",
        )
    try:
        relative = normalize_relative(path)
        source = safe_join(selected_root, relative)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not source.is_file() or source.is_symlink():
        raise HTTPException(status_code=404, detail="Plik nie istnieje")
    if source.suffix.lower() not in {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}:
        raise HTTPException(status_code=415, detail="To nie jest obsługiwany plik audio")
    try:
        file_stat = source.stat()
        duration_seconds, duration = browser_audio_metadata(source, file_stat)
    except OSError as exc:
        raise HTTPException(status_code=403, detail=f"Nie udało się odczytać pliku: {exc}") from exc
    return {
        "root": root,
        "path": relative,
        "duration_seconds": duration_seconds,
        "duration": duration,
    }


@app.post("/api/files/directories")
async def create_directory(
    request: Request, sprawdzacz_edit_session: str | None = Cookie(default=None)
) -> dict[str, str]:
    require_edit(sprawdzacz_edit_session)
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\0" in name:
        raise HTTPException(status_code=422, detail="Podaj poprawną nazwę pojedynczego folderu")
    try:
        parent = normalize_relative(str(body.get("path", "")))
        relative = normalize_relative(f"{parent}/{name}" if parent else name)
        target = safe_join(MEDIA_ROOT, relative)
        target.mkdir()
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="Folder o tej nazwie już istnieje") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Brak uprawnień do utworzenia folderu") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"path": relative}


@app.post("/api/files/infer-pattern")
async def infer_file_pattern(request: Request) -> dict[str, str]:
    body = await request.json()
    try:
        return infer_patterns(str(body.get("path", "")))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/pattern/preview")
async def pattern_preview(request: Request) -> dict[str, str]:
    body = await request.json()
    try:
        day = dt.date.fromisoformat(str(body.get("date", "")))
        value = preview_path(
            str(body.get("folder_pattern", "")), str(body.get("filename_pattern", "")), day
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"path": value}


@app.post("/api/import-xls")
async def import_xls(
    file: UploadFile,
    sprawdzacz_edit_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    require_edit(sprawdzacz_edit_session)
    if not file.filename or not file.filename.lower().endswith(".xls"):
        raise HTTPException(status_code=422, detail="Wybierz plik .xls")
    upload_dir = Path(os.getenv("UPLOAD_TMP", "/tmp/sprawdzacz"))
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / "import.xls"
    target.write_bytes(await file.read())
    try:
        return import_legacy_xls(database, target)
    finally:
        target.unlink(missing_ok=True)
