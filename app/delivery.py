from __future__ import annotations

import asyncio
import datetime as dt
import json
import mimetypes
import os
import smtplib
import ssl
import threading
import time
import uuid
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

try:
    import requests
except ModuleNotFoundError:  # Pakiet jest instalowany w obrazie; pozwala testować konfigurację bez sieci.
    requests = None  # type: ignore[assignment]

from .checker import check_occurrence
from .db import normalize_author_emails
from .patterns import safe_join


GOOGLE_SCOPE_VERSION = 1
DRIVE_SCOPE = (
    "https://www.googleapis.com/auth/userinfo.email "
    "https://www.googleapis.com/auth/drive.file"
)
CALENDAR_SCOPE_VERSION = 1
CALENDAR_SCOPE = (
    "https://www.googleapis.com/auth/userinfo.email "
    "https://www.googleapis.com/auth/calendar.events "
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
)
DEFAULT_CONFIG: dict[str, Any] = {
    "google_client_id": "",
    "google_client_secret": "",
    "google_refresh_token": "",
    "google_connected_email": "",
    "google_scope_version": 0,
    "calendar_client_id": "",
    "calendar_client_secret": "",
    "calendar_redirect_uri": "https://sprawdzacz-oauth.soundcode.pl/",
    "calendar_refresh_token": "",
    "calendar_connected_email": "",
    "calendar_scope_version": 0,
    "calendar_id": "",
    "calendar_name": "",
    "calendar_access_role": "",
    "drive_root_folder_name": "Emaus Hub",
    "drive_root_folder_id": "",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_username": "",
    "smtp_password": "",
    "smtp_from_email": "",
    "smtp_from_name": "Radio Emaus",
    "smtp_security": "starttls",
    "retention_days": 30,
}
_DEVICE_FLOWS: dict[str, dict[str, Any]] = {}
_DEVICE_FLOWS_LOCK = threading.Lock()
_CALENDAR_FLOWS: dict[str, dict[str, Any]] = {}


class DriveRecipientRequiresLinkAccess(RuntimeError):
    """Google rejected a named recipient, but link sharing can still be used."""


def load_delivery_config(path: str | Path) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    target = Path(path)
    if target.is_file():
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                config.update(raw)
        except (OSError, json.JSONDecodeError):
            pass
    return config


def public_delivery_config(path: str | Path) -> dict[str, Any]:
    config = load_delivery_config(path)
    return {
        "google_client_id": config["google_client_id"],
        "google_client_secret_set": bool(config["google_client_secret"]),
        "google_connected": bool(config["google_refresh_token"]),
        "google_connected_email": config["google_connected_email"],
        "google_scope_version": int(config.get("google_scope_version", 0) or 0),
        "calendar_client_id": config.get("calendar_client_id", ""),
        "calendar_client_secret_set": bool(config.get("calendar_client_secret", "")),
        "calendar_redirect_uri": config.get("calendar_redirect_uri", ""),
        "calendar_connected": bool(config.get("calendar_refresh_token", "")),
        "calendar_connected_email": config.get("calendar_connected_email", ""),
        "google_calendar_access": bool(config.get("calendar_refresh_token", "")),
        "calendar_id": config.get("calendar_id", ""),
        "calendar_name": config.get("calendar_name", ""),
        "calendar_access_role": config.get("calendar_access_role", ""),
        "calendar_configured": bool(config.get("calendar_id", "")),
        "drive_root_folder_name": config["drive_root_folder_name"],
        "smtp_host": config["smtp_host"],
        "smtp_port": config["smtp_port"],
        "smtp_username": config["smtp_username"],
        "smtp_password_set": bool(config["smtp_password"]),
        "smtp_from_email": config["smtp_from_email"],
        "smtp_from_name": config["smtp_from_name"],
        "smtp_security": config["smtp_security"],
        "retention_days": config["retention_days"],
        "ready": bool(
            config["google_refresh_token"]
            and config["smtp_host"]
            and config["smtp_from_email"]
        ),
    }


def save_delivery_config(path: str | Path, values: dict[str, Any]) -> dict[str, Any]:
    config = load_delivery_config(path)
    previous_client_id = str(config.get("google_client_id", ""))
    previous_calendar_client_id = str(config.get("calendar_client_id", ""))
    previous_calendar_redirect_uri = str(config.get("calendar_redirect_uri", ""))
    for key in (
        "google_client_id", "drive_root_folder_name", "calendar_id", "calendar_name",
        "calendar_access_role", "calendar_client_id", "calendar_redirect_uri",
        "smtp_host", "smtp_username", "smtp_from_email",
        "smtp_from_name", "smtp_security",
    ):
        if key in values:
            config[key] = str(values.get(key, "")).strip()
    for secret in ("google_client_secret", "calendar_client_secret", "smtp_password"):
        candidate = str(values.get(secret, "")).strip()
        if candidate:
            config[secret] = candidate
    try:
        config["smtp_port"] = int(values.get("smtp_port", config["smtp_port"]))
        config["retention_days"] = int(values.get("retention_days", config["retention_days"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("Port SMTP i retencja muszą być liczbami") from exc
    if config["smtp_port"] not in range(1, 65536):
        raise ValueError("Nieprawidłowy port SMTP")
    if config["retention_days"] not in range(1, 366):
        raise ValueError("Retencja musi wynosić od 1 do 365 dni")
    if config["smtp_security"] not in {"starttls", "ssl", "none"}:
        raise ValueError("Nieprawidłowy tryb zabezpieczenia SMTP")
    if not config["drive_root_folder_name"]:
        config["drive_root_folder_name"] = DEFAULT_CONFIG["drive_root_folder_name"]
    if config["google_client_id"] != previous_client_id:
        config["google_refresh_token"] = ""
        config["google_connected_email"] = ""
        config["google_scope_version"] = 0
        config["drive_root_folder_id"] = ""
    if (
        config["calendar_client_id"] != previous_calendar_client_id
        or config["calendar_redirect_uri"] != previous_calendar_redirect_uri
    ):
        config["calendar_refresh_token"] = ""
        config["calendar_connected_email"] = ""
        config["calendar_scope_version"] = 0
        config["calendar_id"] = ""
        config["calendar_name"] = ""
        config["calendar_access_role"] = ""
    _write_config(path, config)
    return public_delivery_config(path)


def start_google_calendar_flow(path: str | Path) -> dict[str, Any]:
    config = load_delivery_config(path)
    client_id = str(config.get("calendar_client_id", "")).strip()
    client_secret = str(config.get("calendar_client_secret", "")).strip()
    redirect_uri = str(config.get("calendar_redirect_uri", "")).strip()
    if not client_id or not client_secret or not redirect_uri:
        raise ValueError("Podaj Client ID, Client Secret i adres przekierowania dla Kalendarza")
    state = uuid.uuid4().hex
    with _DEVICE_FLOWS_LOCK:
        _CALENDAR_FLOWS[state] = {
            "expires_at": time.time() + 900,
            "config_path": str(path),
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": CALENDAR_SCOPE,
        "access_type": "offline",
        "prompt": "consent select_account",
        "include_granted_scopes": "true",
        "state": state,
    }
    return {
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params),
        "state": state,
        "expires_in": 900,
    }


def finish_google_calendar_flow(path: str | Path, state: str, returned_value: str) -> dict[str, Any]:
    with _DEVICE_FLOWS_LOCK:
        flow = _CALENDAR_FLOWS.pop(state, None)
    if not flow or flow["config_path"] != str(path) or time.time() >= flow["expires_at"]:
        raise ValueError("Sesja łączenia Kalendarza wygasła — rozpocznij ponownie")
    value = str(returned_value or "").strip()
    parsed = urlparse(value)
    query = parse_qs(parsed.query) if parsed.query else {}
    returned_state = str((query.get("state") or [state])[0])
    code = str((query.get("code") or [value])[0])
    if returned_state != state:
        raise ValueError("Nieprawidłowy stan autoryzacji Google")
    if not code or code.startswith("http"):
        raise ValueError("Wklej cały adres strony po zatwierdzeniu Google albo sam kod")
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": flow["client_id"],
            "client_secret": flow["client_secret"],
            "code": code,
            "redirect_uri": flow["redirect_uri"],
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    payload = _json_response(response, "Nie udało się dokończyć łączenia Kalendarza")
    refresh_token = str(payload.get("refresh_token", ""))
    if not refresh_token:
        raise ValueError("Google nie zwrócił tokena Kalendarza. Rozpocznij łączenie ponownie")
    email = ""
    try:
        info = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {payload['access_token']}"}, timeout=20,
        )
        if info.ok:
            email = str(info.json().get("email", ""))
    except requests.RequestException:
        pass
    config = load_delivery_config(path)
    config["calendar_refresh_token"] = refresh_token
    config["calendar_connected_email"] = email
    config["calendar_scope_version"] = CALENDAR_SCOPE_VERSION
    config["calendar_id"] = ""
    config["calendar_name"] = ""
    config["calendar_access_role"] = ""
    _write_config(path, config)
    return {"connected": True, "email": email}


def disconnect_google_calendar(path: str | Path) -> None:
    config = load_delivery_config(path)
    token = str(config.get("calendar_refresh_token", ""))
    if token:
        try:
            requests.post("https://oauth2.googleapis.com/revoke", params={"token": token}, timeout=20)
        except requests.RequestException:
            pass
    for key in ("calendar_refresh_token", "calendar_connected_email", "calendar_id", "calendar_name", "calendar_access_role"):
        config[key] = ""
    config["calendar_scope_version"] = 0
    _write_config(path, config)


def _write_config(path: str | Path, config: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def start_google_device_flow(path: str | Path) -> dict[str, Any]:
    config = load_delivery_config(path)
    if not config["google_client_id"]:
        raise ValueError("Najpierw podaj Google Client ID i zapisz ustawienia")
    response = requests.post(
        "https://oauth2.googleapis.com/device/code",
        data={"client_id": config["google_client_id"], "scope": DRIVE_SCOPE},
        timeout=20,
    )
    payload = _json_response(response, "Nie udało się rozpocząć łączenia z Google")
    flow_id = uuid.uuid4().hex
    flow = {
        "device_code": payload["device_code"],
        "expires_at": time.time() + int(payload.get("expires_in", 1800)),
        "interval": max(5, int(payload.get("interval", 5))),
        "client_id": config["google_client_id"],
        "client_secret": config["google_client_secret"],
        "config_path": str(path),
    }
    with _DEVICE_FLOWS_LOCK:
        _DEVICE_FLOWS[flow_id] = flow
    return {
        "flow_id": flow_id,
        "user_code": payload["user_code"],
        "verification_url": payload.get("verification_url", "https://www.google.com/device"),
        "expires_in": payload.get("expires_in", 1800),
        "interval": flow["interval"],
    }


def poll_google_device_flow(flow_id: str) -> dict[str, Any]:
    with _DEVICE_FLOWS_LOCK:
        flow = _DEVICE_FLOWS.get(flow_id)
    if not flow:
        raise ValueError("Sesja łączenia z Google wygasła")
    if time.time() >= flow["expires_at"]:
        with _DEVICE_FLOWS_LOCK:
            _DEVICE_FLOWS.pop(flow_id, None)
        raise ValueError("Kod Google wygasł — rozpocznij łączenie ponownie")
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": flow["client_id"],
            "client_secret": flow["client_secret"],
            "device_code": flow["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        timeout=20,
    )
    payload = response.json() if response.content else {}
    if not response.ok:
        error = payload.get("error", "")
        if error in {"authorization_pending", "slow_down"}:
            return {"connected": False, "pending": True, "slow_down": error == "slow_down"}
        raise ValueError(payload.get("error_description") or error or "Google odrzucił autoryzację")
    refresh_token = str(payload.get("refresh_token", ""))
    if not refresh_token:
        raise ValueError("Google nie zwrócił tokena odświeżania")
    email = ""
    try:
        info = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
            timeout=20,
        )
        if info.ok:
            email = str(info.json().get("email", ""))
    except requests.RequestException:
        pass
    config = load_delivery_config(flow["config_path"])
    config["google_refresh_token"] = refresh_token
    config["google_connected_email"] = email
    config["google_scope_version"] = GOOGLE_SCOPE_VERSION
    config["drive_root_folder_id"] = ""
    _write_config(flow["config_path"], config)
    with _DEVICE_FLOWS_LOCK:
        _DEVICE_FLOWS.pop(flow_id, None)
    return {"connected": True, "email": email}


def disconnect_google(path: str | Path) -> None:
    config = load_delivery_config(path)
    token = config.get("google_refresh_token", "")
    if token:
        try:
            requests.post("https://oauth2.googleapis.com/revoke", params={"token": token}, timeout=20)
        except requests.RequestException:
            pass
    config["google_refresh_token"] = ""
    config["google_connected_email"] = ""
    config["google_scope_version"] = 0
    config["drive_root_folder_id"] = ""
    _write_config(path, config)


def test_smtp(path: str | Path) -> None:
    config = load_delivery_config(path)
    recipient = config["smtp_from_email"] or config["smtp_username"]
    if not recipient:
        raise ValueError("Podaj adres nadawcy SMTP")
    _send_mail(
        config,
        recipient,
        "Test — Emaus Hub",
        "Połączenie SMTP działa poprawnie.",
    )


class DriveClient:
    def __init__(self, config_path: str | Path):
        self.config_path = str(config_path)
        self.config = load_delivery_config(config_path)
        if not self.config["google_refresh_token"]:
            raise ValueError("Google Drive nie jest połączony")
        response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self.config["google_client_id"],
                "client_secret": self.config["google_client_secret"],
                "refresh_token": self.config["google_refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        payload = _json_response(response, "Nie udało się odświeżyć dostępu do Google Drive")
        self.headers = {"Authorization": f"Bearer {payload['access_token']}"}

    def ensure_root_folder(self) -> str:
        folder_id = str(self.config.get("drive_root_folder_id", ""))
        if folder_id:
            return folder_id
        folder = self.create_folder(self.config["drive_root_folder_name"], None)
        self.config["drive_root_folder_id"] = folder["id"]
        _write_config(self.config_path, self.config)
        return folder["id"]

    def create_folder(self, name: str, parent_id: str | None) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]
        response = requests.post(
            "https://www.googleapis.com/drive/v3/files",
            params={"fields": "id,name,webViewLink"},
            headers={**self.headers, "Content-Type": "application/json"},
            json=metadata,
            timeout=30,
        )
        return _json_response(response, "Nie udało się utworzyć folderu na Google Drive")

    def share_folder(self, folder_id: str, email: str) -> str:
        response = requests.post(
            f"https://www.googleapis.com/drive/v3/files/{folder_id}/permissions",
            params={"sendNotificationEmail": "false", "fields": "id"},
            headers={**self.headers, "Content-Type": "application/json"},
            json={"type": "user", "role": "reader", "emailAddress": email},
            timeout=30,
        )
        if not response.ok:
            payload = _response_payload(response)
            detail = _response_error_detail(response, payload)
            message = f"Nie udało się udostępnić folderu autorowi: {detail}"
            if _recipient_requires_link_access(response, payload, detail):
                raise DriveRecipientRequiresLinkAccess(message)
            raise RuntimeError(message)
        return str(_json_response(response, "Nie udało się udostępnić folderu autorowi")["id"])

    def share_folder_by_link(self, folder_id: str) -> str:
        """Allow unlisted read access for recipients who cannot receive user permissions."""
        existing_response = requests.get(
            f"https://www.googleapis.com/drive/v3/files/{folder_id}/permissions",
            params={"fields": "permissions(id,type,role,allowFileDiscovery)"},
            headers=self.headers,
            timeout=30,
        )
        existing = _json_response(
            existing_response,
            "Nie udało się sprawdzić dostępu do folderu przez link",
        )
        for permission in existing.get("permissions", []):
            if (
                isinstance(permission, dict)
                and permission.get("type") == "anyone"
                and permission.get("role") == "reader"
                and permission.get("id")
            ):
                return str(permission["id"])
        response = requests.post(
            f"https://www.googleapis.com/drive/v3/files/{folder_id}/permissions",
            params={"fields": "id"},
            headers={**self.headers, "Content-Type": "application/json"},
            json={
                "type": "anyone",
                "role": "reader",
                "allowFileDiscovery": False,
            },
            timeout=30,
        )
        return str(
            _json_response(
                response,
                "Nie udało się włączyć dostępu do folderu przez link",
            )["id"]
        )

    def delete_permission(self, folder_id: str, permission_id: str) -> None:
        if not permission_id:
            return
        response = requests.delete(
            f"https://www.googleapis.com/drive/v3/files/{folder_id}/permissions/{permission_id}",
            headers=self.headers,
            timeout=30,
        )
        if response.status_code not in {204, 404}:
            _json_response(response, "Nie udało się usunąć starego udostępnienia")

    def upload_file(self, source: Path, folder_id: str) -> dict[str, Any]:
        existing_id = self._find_file(source.name, folder_id)
        metadata: dict[str, Any] = {"name": source.name}
        method = requests.patch if existing_id else requests.post
        url = (
            f"https://www.googleapis.com/upload/drive/v3/files/{existing_id}"
            if existing_id else "https://www.googleapis.com/upload/drive/v3/files"
        )
        if not existing_id:
            metadata["parents"] = [folder_id]
        content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        response = method(
            url,
            params={"uploadType": "resumable", "fields": "id,name,webViewLink,createdTime"},
            headers={
                **self.headers,
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": content_type,
                "X-Upload-Content-Length": str(source.stat().st_size),
            },
            json=metadata,
            timeout=30,
        )
        if not response.ok or "Location" not in response.headers:
            _json_response(response, f"Nie udało się rozpocząć wysyłania {source.name}")
            raise RuntimeError("Google nie zwrócił adresu uploadu")
        with source.open("rb") as handle:
            uploaded = requests.put(
                response.headers["Location"],
                headers={"Content-Type": content_type, "Content-Length": str(source.stat().st_size)},
                data=handle,
                timeout=(30, 60 * 60),
            )
        return _json_response(uploaded, f"Nie udało się wysłać {source.name}")

    def cleanup_folder(self, folder_id: str, retention_days: int) -> int:
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=retention_days)).isoformat().replace("+00:00", "Z")
        query = f"'{folder_id}' in parents and trashed=false and modifiedTime < '{cutoff}'"
        items = self._list_files(query, "files(id,name,modifiedTime,mimeType)")
        deleted = 0
        for item in items:
            if item.get("mimeType") == "application/vnd.google-apps.folder":
                continue
            response = requests.delete(
                f"https://www.googleapis.com/drive/v3/files/{item['id']}",
                headers=self.headers,
                timeout=30,
            )
            if response.status_code in {204, 404}:
                deleted += 1
        return deleted

    def _find_file(self, name: str, folder_id: str) -> str:
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        query = f"'{folder_id}' in parents and name='{escaped}' and trashed=false"
        items = self._list_files(query, "files(id,name)")
        return str(items[0]["id"]) if items else ""

    def _list_files(self, query: str, fields: str) -> list[dict[str, Any]]:
        response = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            params={"q": query, "fields": f"nextPageToken,{fields}", "pageSize": 1000},
            headers=self.headers,
            timeout=30,
        )
        return list(_json_response(response, "Nie udało się odczytać Google Drive").get("files", []))


def send_show_to_author(
    database: Any,
    show: dict[str, Any],
    day: dt.date,
    media_root: Path,
    config_path: str | Path,
) -> dict[str, Any]:
    if not show.get("send_to_author") or not show.get("author_email"):
        raise ValueError("Dla tej audycji nie włączono wysyłki do autora")
    recipients = normalize_author_emails(show["author_email"])
    if not recipients:
        raise ValueError("Dla tej audycji nie podano adresu e-mail autora")
    deliveries = database.successful_author_deliveries(day.isoformat())
    previous_deliveries = {
        recipient.casefold(): deliveries.get((int(show["id"]), recipient.casefold()))
        for recipient in recipients
    }
    pending_recipients = [
        recipient for recipient in recipients if not previous_deliveries[recipient.casefold()]
    ]
    if not pending_recipients:
        previous = next(
            delivery for delivery in previous_deliveries.values() if delivery is not None
        )
        return {
            "sent": True,
            "already_sent": True,
            "recipient": ", ".join(recipients),
            "recipients": recipients,
            "sent_recipients": [],
            "already_sent_recipients": recipients,
            "files": previous["files"],
            "folder_url": previous["folder_url"],
            "link_access": bool(show.get("drive_link_permission_id")),
        }
    occurrence = check_occurrence(show, show, day, media_root)
    missing = [part for part in occurrence["parts"] if not part["found"]]
    if missing:
        raise FileNotFoundError("Nie można wysłać audycji — brakuje co najmniej jednego pliku")
    sources = [safe_join(media_root, part["relative_path"]) for part in occurrence["parts"]]
    filenames = [source.name for source in sources]
    folder_url = ""
    try:
        client = DriveClient(config_path)
        folder_id = str(show.get("drive_folder_id", ""))
        link_permission_id = str(show.get("drive_link_permission_id", "")).strip()
        link_fallback_recipients: list[str] = []
        raw_permissions = show.get("drive_permissions", {})
        tracked_permissions: dict[str, dict[str, str]] = {}
        if isinstance(raw_permissions, dict):
            for email, permission_id in raw_permissions.items():
                try:
                    normalized = normalize_author_emails(str(email))
                except ValueError:
                    continue
                if normalized and str(permission_id).strip():
                    tracked_permissions[normalized[0].casefold()] = {
                        "email": normalized[0],
                        "permission_id": str(permission_id).strip(),
                    }
        if not folder_id:
            root_id = client.ensure_root_folder()
            folder_id = client.create_folder(str(show["name"]), root_id)["id"]
            tracked_permissions = {}
            link_permission_id = ""
            database.set_drive_folder(show["id"], folder_id, {}, link_permission_id)

        def persist_permissions() -> None:
            database.set_drive_folder(
                show["id"],
                folder_id,
                {
                    item["email"]: item["permission_id"]
                    for item in tracked_permissions.values()
                },
                link_permission_id,
            )

        recipient_keys = {recipient.casefold() for recipient in recipients}
        for key, item in list(tracked_permissions.items()):
            if key in recipient_keys:
                continue
            client.delete_permission(folder_id, item["permission_id"])
            tracked_permissions.pop(key, None)
            persist_permissions()
        for recipient in recipients:
            key = recipient.casefold()
            if key in tracked_permissions:
                continue
            try:
                permission_id = client.share_folder(folder_id, recipient)
            except DriveRecipientRequiresLinkAccess:
                link_fallback_recipients.append(recipient)
            else:
                tracked_permissions[key] = {
                    "email": recipient,
                    "permission_id": permission_id,
                }
                persist_permissions()
        if link_fallback_recipients and not link_permission_id:
            link_permission_id = client.share_folder_by_link(folder_id)
            persist_permissions()
        uploaded = [client.upload_file(source, folder_id) for source in sources]
        folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
        config = load_delivery_config(config_path)
        client.cleanup_folder(folder_id, int(config["retention_days"]))
        file_lines = "\n".join(f"• {item['name']}" for item in uploaded)
        retention_days = int(config["retention_days"])
        link_access_note = (
            "\nLink działa bez logowania do konta Google. Dostęp ma każda osoba, "
            "która otrzyma ten link.\n"
            if link_permission_id
            else ""
        )
        message = (
            "Cześć,\n\n"
            f"udostępniono Ci {('nowy plik' if len(uploaded) == 1 else 'nowe pliki')} audycji „{show['name']}”:\n"
            f"{file_lines}\n\n"
            f"Folder Google Drive:\n{folder_url}\n\n"
            f"{link_access_note}"
            f"Plik będzie dostępny w tym folderze przez {retention_days} dni.\n\n"
            "Pozdrawiamy\nRadio Emaus"
        )
        subject = f"Nowa audycja: {show['name']} — {day.isoformat()}"
    except Exception as exc:
        for recipient in pending_recipients:
            database.record_author_delivery(
                show["id"], day.isoformat(), recipient, "failed", filenames, folder_url, str(exc)
            )
        raise

    sent_recipients: list[str] = []
    failed_recipients: list[tuple[str, str]] = []
    for recipient in pending_recipients:
        try:
            _send_mail(config, recipient, subject, message)
            database.record_author_delivery(
                show["id"], day.isoformat(), recipient, "sent", filenames, folder_url
            )
            sent_recipients.append(recipient)
        except Exception as exc:
            database.record_author_delivery(
                show["id"], day.isoformat(), recipient, "failed", filenames, folder_url, str(exc)
            )
            failed_recipients.append((recipient, str(exc)))
    if failed_recipients:
        failed = ", ".join(recipient for recipient, _ in failed_recipients)
        sent_note = f" Wysłano poprawnie do: {', '.join(sent_recipients)}." if sent_recipients else ""
        raise RuntimeError(f"Nie udało się wysłać wiadomości do: {failed}.{sent_note}")
    already_sent_recipients = [
        recipient for recipient in recipients if previous_deliveries[recipient.casefold()]
    ]
    return {
        "sent": True,
        "already_sent": False,
        "recipient": ", ".join(recipients),
        "recipients": recipients,
        "sent_recipients": sent_recipients,
        "already_sent_recipients": already_sent_recipients,
        "files": filenames,
        "folder_url": folder_url,
        "link_access": bool(link_permission_id),
        "link_fallback_recipients": link_fallback_recipients,
    }


def cleanup_drive_files(database: Any, config_path: str | Path) -> int:
    config = load_delivery_config(config_path)
    if not config.get("google_refresh_token"):
        return 0
    client = DriveClient(config_path)
    deleted = 0
    for show in database.list_shows(include_inactive=True):
        folder_id = str(show.get("drive_folder_id", ""))
        if folder_id:
            deleted += client.cleanup_folder(folder_id, int(config["retention_days"]))
    return deleted


async def drive_cleanup_loop(database: Any, config_path: str | Path) -> None:
    while True:
        try:
            await asyncio.to_thread(cleanup_drive_files, database, config_path)
        except Exception:
            pass
        await asyncio.sleep(24 * 60 * 60)


def _send_mail(config: dict[str, Any], recipient: str, subject: str, body: str) -> None:
    if not config.get("smtp_host") or not config.get("smtp_from_email"):
        raise ValueError("Skonfiguruj SMTP w Ustawieniach")
    message = EmailMessage()
    message["From"] = f"{config['smtp_from_name']} <{config['smtp_from_email']}>" if config.get("smtp_from_name") else config["smtp_from_email"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    security = config.get("smtp_security", "starttls")
    smtp_class = smtplib.SMTP_SSL if security == "ssl" else smtplib.SMTP
    with smtp_class(config["smtp_host"], int(config["smtp_port"]), timeout=30) as server:
        if security == "starttls":
            server.starttls(context=ssl.create_default_context())
        if config.get("smtp_username"):
            server.login(config["smtp_username"], config.get("smtp_password", ""))
        server.send_message(message)


def _response_payload(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _response_error_detail(response: requests.Response, payload: dict[str, Any]) -> str:
    detail = payload.get("error_description")
    if not detail and isinstance(payload.get("error"), dict):
        detail = payload["error"].get("message")
    if not detail:
        detail = str(payload.get("error") or response.text[:300] or response.status_code)
    return str(detail)


def _recipient_requires_link_access(
    response: requests.Response, payload: dict[str, Any], detail: str
) -> bool:
    if response.status_code not in {400, 403}:
        return False
    reasons: set[str] = set()
    error = payload.get("error")
    if isinstance(error, dict):
        for item in error.get("errors", []):
            if isinstance(item, dict) and item.get("reason"):
                reasons.add(str(item["reason"]).casefold())
    normalized = detail.casefold()
    account_markers = (
        "does not have a google account",
        "doesn't have a google account",
        "doesn’t have a google account",
        "nie ma on konta google",
        "nie ma konta google",
        "non-google account",
    )
    return "invalidsharingrequest" in reasons or any(
        marker in normalized for marker in account_markers
    )


def _json_response(response: requests.Response, prefix: str) -> dict[str, Any]:
    payload = _response_payload(response)
    if not response.ok:
        detail = _response_error_detail(response, payload)
        raise RuntimeError(f"{prefix}: {detail}")
    return payload
