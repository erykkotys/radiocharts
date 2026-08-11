from __future__ import annotations

import hashlib
import html as html_lib
import re
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

CURRENT_URL = "https://www.rmf.fm/poplista.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

CONTROL = {
    "propozycje", "lubisz – popieraj!", "lubisz - popieraj!",
    "nie lubisz – odrzucaj!", "nie lubisz - odrzucaj!",
}
ISSUE_RE = re.compile(r"(?:Notowanie\s+)?(\d{3,5})\s*/\s*(\d{4}-\d{2}-\d{2})", re.I)


def _tokens(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    return [re.sub(r"\s+", " ", x).strip() for x in soup.stripped_strings if x.strip()]


def _find_issue(html: str, tokens: list[str]) -> tuple[int | None, int, date]:
    for i, tok in enumerate(tokens):
        m = ISSUE_RE.fullmatch(tok)
        if m:
            return i, int(m.group(1)), date.fromisoformat(m.group(2))
    for i in range(len(tokens) - 2):
        if re.fullmatch(r"\d{3,5}", tokens[i]) and tokens[i + 1] == "/" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", tokens[i + 2]):
            return i, int(tokens[i]), date.fromisoformat(tokens[i + 2])
    joined = " ".join(tokens)
    m = ISSUE_RE.search(joined)
    if m:
        idx = next((i for i, t in enumerate(tokens) if str(m.group(1)) in t), None)
        return idx, int(m.group(1)), date.fromisoformat(m.group(2))
    raw = html_lib.unescape(html)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"\s+", " ", raw)
    m = ISSUE_RE.search(raw)
    if m:
        return None, int(m.group(1)), date.fromisoformat(m.group(2))
    raise ValueError("Nie znaleziono numeru/data notowania RMF")


def parse_rmf(html: str) -> dict:
    tokens = _tokens(html)
    issue_idx, issue_no, chart_date = _find_issue(html, tokens)
    if issue_idx is None:
        issue_idx = next((i for i, t in enumerate(tokens) if str(issue_no) in t), -1)
    stream = tokens[issue_idx + 1 :] if issue_idx >= 0 else tokens
    entries = []
    cursor = 0
    for pos in range(1, 21):
        found = None
        for j in range(cursor, len(stream)):
            low = stream[j].lower()
            if low in CONTROL or low == "propozycje":
                break
            if stream[j] == str(pos):
                found = j
                break
        if found is None:
            break
        values = []
        k = found + 1
        while k < len(stream) and len(values) < 2:
            v = stream[k].strip()
            low = v.lower()
            if low == "propozycje":
                break
            if v and not re.fullmatch(r"\d+", v) and low not in {"tak", "nie", "głosuj", "glosuj", "wpisz numer notowania"}:
                values.append(v)
            k += 1
        if len(values) < 2:
            break
        entries.append({"position": pos, "artist": values[0], "title": values[1]})
        cursor = k
    if len(entries) < 10:
        raise ValueError(f"Parser RMF odczytał tylko {len(entries)} pozycji; strona mogła zmienić strukturę")
    return {"source": "RMF", "chart_date": chart_date, "issue_key": str(issue_no), "chart_size": 20, "entries": entries}


def _new_session(timeout: int = 25) -> requests.Session:
    session = requests.Session()
    try:
        session.get("https://www.rmf.fm/", timeout=min(timeout, 10), headers=HEADERS, allow_redirects=True)
    except requests.RequestException:
        pass
    return session


def _detected_issue(response) -> int | None:
    try:
        _, no, _ = _find_issue(response.text, _tokens(response.text))
        return no
    except Exception:
        return None


def _archive_form(html: str, base_url: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    target = None
    for inp in soup.find_all("input"):
        hint = " ".join(filter(None, [inp.get("placeholder"), inp.get("aria-label"), inp.get("name"), inp.get("id")]))
        if "notowania" in hint.lower() or ("numer" in hint.lower() and "notow" in hint.lower()):
            target = inp
            break
    if target is None:
        return None
    form = target.find_parent("form")
    if form is None:
        return {"field": target.get("name") or target.get("id"), "method": None, "action": None, "hidden": {}}
    hidden = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if name and inp.get("type", "").lower() in {"hidden", "submit"} and inp.get("value") is not None:
            hidden[name] = inp.get("value")
    return {
        "field": target.get("name") or target.get("id"),
        "method": (form.get("method") or "get").lower(),
        "action": urljoin(base_url, form.get("action") or base_url),
        "hidden": hidden,
    }


def _request_current(session: requests.Session, timeout: int):
    return session.get(CURRENT_URL, timeout=timeout, headers=HEADERS, allow_redirects=True)


def _request_archive(session: requests.Session, current_response, issue: int, timeout: int):
    """Fetch one historical RMF Poplista issue.

    RMF exposes archive issues as stable public pages such as
    ``/poplista,6178.html``.  Older query-string variants currently return the
    newest issue and therefore must not be used for backfill.
    """
    archive_url = f"https://www.rmf.fm/poplista,{int(issue)}.html"
    attempts = []
    try:
        r = session.get(archive_url, timeout=timeout, headers=HEADERS, allow_redirects=True)
        detected = _detected_issue(r)
        attempts.append({
            "kind": "archive_path",
            "url": r.url,
            "status": r.status_code,
            "detected": detected,
        })
        if r.ok and detected == issue:
            return r, attempts
    except requests.RequestException as exc:
        attempts.append({"kind": "archive_path", "url": archive_url, "error": str(exc)})

    # Keep live-form discovery only as a diagnostic fallback in case RMF changes
    # the archive route again.  We never accept a response unless its issue
    # number exactly matches the requested one.
    form = _archive_form(current_response.text, current_response.url)
    if form and form.get("field"):
        payload = dict(form.get("hidden") or {})
        payload[form["field"]] = str(issue)
        try:
            if form.get("method") == "post":
                r = session.post(form.get("action") or CURRENT_URL, data=payload, timeout=timeout, headers=HEADERS, allow_redirects=True)
            else:
                r = session.get(form.get("action") or CURRENT_URL, params=payload, timeout=timeout, headers=HEADERS, allow_redirects=True)
            detected = _detected_issue(r)
            attempts.append({
                "kind": "form_fallback", "method": form.get("method"),
                "url": r.url, "status": r.status_code, "detected": detected,
            })
            if r.ok and detected == issue:
                return r, attempts
        except requests.RequestException as exc:
            attempts.append({"kind": "form_fallback", "error": str(exc)})

    return current_response, attempts

def _request_rmf(issue: int | None = None, timeout: int = 25):
    with _new_session(timeout) as session:
        current = _request_current(session, timeout)
        if issue is None:
            return current
        r, _ = _request_archive(session, current, issue, timeout)
        return r


def probe_rmf(timeout: int = 25, probe_archive: bool = True) -> dict:
    with _new_session(timeout) as session:
        r = _request_current(session, timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        title = soup.title.get_text(" ", strip=True) if soup.title else "(brak title)"
        tokens = _tokens(r.text)
        issue = None
        current_no = None
        try:
            _, current_no, d = _find_issue(r.text, tokens)
            issue = f"{current_no} / {d.isoformat()}"
        except ValueError:
            pass
        form = _archive_form(r.text, r.url)
        archive_test = None
        if probe_archive and current_no and current_no > 1:
            _, attempts = _request_archive(session, r, current_no - 1, timeout)
            archive_test = {"requested": current_no - 1, "attempts": attempts}
        return {
            "http_status": r.status_code,
            "url": r.url,
            "content_type": r.headers.get("content-type", ""),
            "bytes": len(r.content),
            "title": title,
            "detected_issue": issue,
            "archive_form": form,
            "archive_test": archive_test,
            "body_sha256": hashlib.sha256(r.content).hexdigest()[:16],
            "visible_start": " | ".join(tokens[:25]),
        }


def fetch_rmf(issue: int | None = None, timeout: int = 25) -> dict:
    with _new_session(timeout) as session:
        current = _request_current(session, timeout)
        current.raise_for_status()
        if issue is None:
            r = current
        else:
            r, attempts = _request_archive(session, current, issue, timeout)
            r.raise_for_status()
            if _detected_issue(r) != issue:
                compact = attempts[-6:]
                raise ValueError(f"RMF nie udostępnił notowania {issue} przez wykryty formularz/fallbacki. Próby={compact}")
        try:
            data = parse_rmf(r.text)
        except ValueError as exc:
            soup = BeautifulSoup(r.text, "lxml")
            title = soup.title.get_text(" ", strip=True) if soup.title else "(brak title)"
            visible = " | ".join(_tokens(r.text)[:12])
            raise ValueError(f"{exc}. HTTP {r.status_code}, URL={r.url}, title={title!r}, początek strony={visible!r}") from exc
        data["source_url"] = r.url
        if issue is not None and str(data["issue_key"]) != str(issue):
            raise ValueError(f"RMF zwrócił notowanie {data['issue_key']} zamiast żądanego {issue}")
        return data
