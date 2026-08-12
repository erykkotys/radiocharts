from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from radiocharts.sources.browser import download_by_text, render_page

URLS = {
    "OLIA": "https://www.olis.pl/charts/oficjalna-lista-airplay",
    "OLIS": "https://www.olis.pl/charts/oficjalna-lista-sprzedazy/single-w-streamie",
}

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

DATE_RANGE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})")
INT_RE = re.compile(r"^\d{1,3}$")

NOISE = {
    "bez zmian na liście", "bez zmian na liscie", "nowość", "nowosc", "wzrost", "spadek",
    "pozycja", "okładka", "okladka", "wykonawca", "tytuł", "tytul", "wydawca/dystrybutor",
    "wydawca / dystrybutor", "wydawca", "dystrybutor", "informacje", "x",
}


def _norm(value: object) -> str:
    s = str(value).strip().lower()
    s = s.replace("ł", "l").replace("ó", "o").replace("ą", "a").replace("ę", "e")
    s = s.replace("ś", "s").replace("ć", "c").replace("ń", "n").replace("ż", "z").replace("ź", "z")
    return re.sub(r"\s+", " ", s)


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [" ".join(str(x) for x in col if str(x) != "nan").strip() for col in df.columns]
    return df


def _find_col(columns, needles: tuple[str, ...]):
    for col in columns:
        n = _norm(col)
        if any(needle in n for needle in needles):
            return col
    return None


def _parse_date_range(text: str) -> tuple[str, str]:
    m = DATE_RANGE_RE.search(re.sub(r"\s+", " ", text))
    if not m:
        raise ValueError("Nie znaleziono zakresu dat OLiA/OLiS")
    start = datetime.strptime(m.group(1), "%d.%m.%Y").date().isoformat()
    end = datetime.strptime(m.group(2), "%d.%m.%Y").date().isoformat()
    return start, end


def _extract_reported_info(raw: object) -> tuple[int | None, int | None]:
    text = re.sub(r"\s+", " ", str(raw))
    weeks = peak = None
    mw = re.search(r"TYGODNIE\s+NA\s+DANEJ\s+LI[ŚS]CIE\s*(\d+)", text, re.I)
    mp = re.search(r"NAJWY[ŻZ]SZA\s+POZYCJA\s+NA\s+LI[ŚS]CIE\s*(\d+)", text, re.I)
    if mw:
        weeks = int(mw.group(1))
    if mp:
        peak = int(mp.group(1))
    return weeks, peak


def _parse_table(html: str) -> list[dict]:
    """Fallback for a future/static table version of the site."""
    try:
        tables = pd.read_html(StringIO(html))
    except (ValueError, ImportError):
        return []

    for table in tables:
        table = _flatten_columns(table)
        pos_col = _find_col(table.columns, ("pozycja", "miejsce", "position", "rank"))
        title_col = _find_col(table.columns, ("tytul", "tytuł", "title"))
        artist_col = _find_col(table.columns, ("wykonawca", "artist"))
        if pos_col is None or title_col is None or artist_col is None:
            continue
        info_col = _find_col(table.columns, ("informacje", "info"))
        entries = []
        for _, row in table.iterrows():
            m = re.search(r"\b(\d{1,3})\b", str(row.get(pos_col, "")))
            if not m:
                continue
            pos = int(m.group(1))
            if not 1 <= pos <= 100:
                continue
            title = str(row.get(title_col, "")).strip()
            artist = str(row.get(artist_col, "")).strip()
            if not title or title.lower() == "nan" or not artist or artist.lower() == "nan":
                continue
            entry = {"position": pos, "artist": artist, "title": title}
            if info_col is not None:
                weeks, peak = _extract_reported_info(row.get(info_col, ""))
                if weeks is not None:
                    entry["reported_weeks"] = weeks
                if peak is not None:
                    entry["reported_peak"] = peak
            entries.append(entry)
        if len(entries) >= 10:
            by_pos = {e["position"]: e for e in entries}
            return [by_pos[p] for p in sorted(by_pos)]
    return []


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def _is_int(line: str) -> bool:
    return bool(INT_RE.fullmatch(line.strip()))


def _is_chart_position(lines: list[str], idx: int, expected: int) -> bool:
    """Detect the *current* rank, not one of the numeric metadata values.

    The rendered OLiA/OLiS cards are effectively:
      rank, title, artist, publisher(s), [previous rank], weeks, peak

    All metadata labels are hidden in the body's innerText, so the reliable
    distinction is that a real current rank is followed by a textual title.
    Metadata numbers are followed by another number until the next card.
    """
    if idx < 0 or idx >= len(lines) or lines[idx] != str(expected):
        return False
    if idx + 1 >= len(lines):
        return False
    nxt = lines[idx + 1].strip()
    if _is_int(nxt):
        return False
    n = _norm(nxt)
    if n in NOISE or n.startswith("tydzien ") or DATE_RANGE_RE.search(nxt):
        return False
    if nxt in {"<", ">"}:
        return False
    return True


def _chart_start(lines: list[str]) -> int:
    # The most stable anchor in the rendered body is "Tydzień NN".
    for i, line in enumerate(lines):
        if re.fullmatch(r"Tydzień\s+\d+", line, re.I):
            return i + 1
    # Fallback to the current date-range controls.
    for i in range(len(lines)):
        if DATE_RANGE_RE.search(" ".join(lines[i : i + 2])):
            return i + 1
    return 0


def _find_markers(lines: list[str], max_position: int = 100) -> list[tuple[int, int]]:
    markers: list[tuple[int, int]] = []
    cursor = _chart_start(lines)
    for expected in range(1, max_position + 1):
        found = None
        for i in range(cursor, len(lines)):
            if _is_chart_position(lines, i, expected):
                found = i
                break
        if found is None:
            break
        markers.append((expected, found))
        cursor = found + 1
    return markers


def _parse_card(pos: int, block: list[str]) -> dict | None:
    """Parse one rendered OLiA/OLiS card from lines between rank markers."""
    cleaned: list[str] = []
    for raw in block:
        line = raw.strip()
        n = _norm(line)
        if not line or n in NOISE:
            continue
        if n.startswith("bez zmian") or n.startswith("nowosc") or n.startswith("wzrost") or n.startswith("spadek"):
            continue
        if re.fullmatch(r"[▲▼△▽+\-–—]+(?:\s*\d+)?", line):
            continue
        cleaned.append(line)

    # The first two textual values are consistently title and artist on the
    # live site. Publisher/distributor text follows them.
    text_values = [x for x in cleaned if not _is_int(x)]
    if len(text_values) < 2:
        return None
    title, artist = text_values[0], text_values[1]

    # At the end of the card OLiA/OLiS expose numeric metadata without labels:
    #   unchanged/new: weeks, peak
    #   moved:         previous_position, weeks, peak
    numeric_tail: list[int] = []
    for line in reversed(cleaned):
        if _is_int(line):
            numeric_tail.append(int(line))
        elif numeric_tail:
            break
    numeric_tail.reverse()

    entry: dict = {"position": pos, "artist": artist, "title": title}
    if len(numeric_tail) >= 2:
        entry["reported_weeks"] = numeric_tail[-2]
        entry["reported_peak"] = numeric_tail[-1]
    if len(numeric_tail) >= 3:
        prev = numeric_tail[-3]
        if 1 <= prev <= 100:
            entry["previous_position"] = prev
    return entry


def _parse_rendered_text(text: str, max_position: int = 100) -> list[dict]:
    lines = _lines(text)
    markers = _find_markers(lines, max_position=max_position)
    entries: list[dict] = []
    for mi, (pos, idx) in enumerate(markers):
        end = markers[mi + 1][1] if mi + 1 < len(markers) else min(len(lines), idx + 40)
        entry = _parse_card(pos, lines[idx + 1 : end])
        if entry:
            entries.append(entry)
    return entries


def parse_olis_rendered(html: str, text: str, source: str) -> dict:
    source = source.upper()
    if source not in URLS:
        raise ValueError(f"Nieznane źródło: {source}")
    start_date, end_date = _parse_date_range(text)
    entries = _parse_table(html)
    parser_mode = "table"
    if len(entries) < 10:
        entries = _parse_rendered_text(text, max_position=100)
        parser_mode = "rendered_text_v2"
    if len(entries) < 10:
        raise ValueError(f"Parser {source} odczytał tylko {len(entries)} pozycji po renderowaniu JS")
    return {
        "source": source,
        "chart_date": end_date,
        "issue_key": f"{start_date}_{end_date}",
        "chart_size": 100,
        "entries": entries,
        "parser_mode": parser_mode,
    }




def _decode_export(content: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _parse_export_csv(content: bytes) -> list[dict]:
    """Parse the official OLiA/OLiS CSV export using tolerant column aliases."""
    text = _decode_export(content)
    candidates: list[pd.DataFrame] = []
    # Auto-sniff delimiter first; then common Polish CSV delimiters.
    for kwargs in (
        {"sep": None, "engine": "python"},
        {"sep": ";", "engine": "python"},
        {"sep": ",", "engine": "python"},
        {"sep": "\t", "engine": "python"},
    ):
        try:
            df = pd.read_csv(StringIO(text), **kwargs)
            if not df.empty:
                candidates.append(_flatten_columns(df))
        except Exception:
            pass
    for df in candidates:
        pos_col = _find_col(df.columns, ("pozycja", "miejsce", "position", "rank", "lp"))
        title_col = _find_col(df.columns, ("tytul", "tytuł", "title"))
        artist_col = _find_col(df.columns, ("wykonawca", "artist"))
        if pos_col is None or title_col is None or artist_col is None:
            continue
        weeks_col = _find_col(df.columns, ("tygodnie", "weeks"))
        peak_col = _find_col(df.columns, ("najwyzsza", "najwyższa", "peak"))
        prev_col = _find_col(df.columns, ("poprzednia", "previous", "last week", "lw"))
        entries: list[dict] = []
        for _, row in df.iterrows():
            m = re.search(r"\b(\d{1,3})\b", str(row.get(pos_col, "")))
            if not m:
                continue
            pos = int(m.group(1))
            if not 1 <= pos <= 100:
                continue
            title = str(row.get(title_col, "")).strip()
            artist = str(row.get(artist_col, "")).strip()
            if not title or title.lower() == "nan" or not artist or artist.lower() == "nan":
                continue
            e: dict = {"position": pos, "artist": artist, "title": title}
            for col, key in ((weeks_col, "reported_weeks"), (peak_col, "reported_peak"), (prev_col, "previous_position")):
                if col is None:
                    continue
                mm = re.search(r"\b(\d{1,3})\b", str(row.get(col, "")))
                if mm:
                    e[key] = int(mm.group(1))
            entries.append(e)
        by_pos = {e["position"]: e for e in entries}
        if len(by_pos) >= 10:
            return [by_pos[p] for p in sorted(by_pos)]
    return []


def _try_official_export(source: str, timeout_ms: int = 45000) -> tuple[list[dict], dict]:
    """Try the official CSV export exposed by OLiA/OLiS."""
    meta: dict = {"attempted": True}
    try:
        exported = download_by_text(URLS[source.upper()], labels=("CSV",), timeout_ms=timeout_ms)
        meta.update({
            "filename": exported.filename,
            "bytes": len(exported.content),
            "via": exported.via,
            "url": exported.url,
            "head": _decode_export(exported.content)[:700],
        })
        entries = _parse_export_csv(exported.content)
        meta["parsed_entries"] = len(entries)
        return entries, meta
    except Exception as exc:
        meta["error"] = f"{type(exc).__name__}: {exc}"
        return [], meta


def _request(source: str, timeout: int = 30):
    source = source.upper()
    if source not in URLS:
        raise ValueError(f"Nieznane źródło: {source}")
    return requests.get(URLS[source], headers=HEADERS, timeout=timeout, allow_redirects=True)


def _render(source: str):
    return render_page(URLS[source.upper()], click_texts=["zobacz pełną listę"], auto_scroll=True)


def probe_olis(source: str, timeout: int = 30) -> dict:
    source = source.upper()
    r = _request(source, timeout=timeout)
    r.raise_for_status()
    raw_soup = BeautifulSoup(r.text, "lxml")
    raw_visible = re.sub(r"\s+", " ", raw_soup.get_text(" ", strip=True))
    scripts = [s.get("src") for s in raw_soup.find_all("script") if s.get("src")][:12]

    rendered = None
    parsed_entries = None
    parse_error = None
    date_range = None
    parser_mode = None
    preview = None
    rendered_lines: list[str] = []
    try:
        rendered = _render(source)
        rendered_lines = _lines(rendered.text)
        start, end = _parse_date_range(rendered.text)
        date_range = f"{start} → {end}"
        parsed = parse_olis_rendered(rendered.html, rendered.text, source)
        parsed_entries = len(parsed["entries"])
        parser_mode = parsed.get("parser_mode")
        preview = parsed["entries"][:5]
    except Exception as exc:
        parse_error = f"{type(exc).__name__}: {exc}"

    export_meta = None
    export_preview = None
    if (parsed_entries or 0) < 50:
        export_entries, export_meta = _try_official_export(source)
        if export_entries:
            export_preview = export_entries[:5]

    return {
        "source": source,
        "http_status": r.status_code,
        "url": r.url,
        "content_type": r.headers.get("content-type", ""),
        "bytes": len(r.content),
        "raw_has_chart": bool(DATE_RANGE_RE.search(raw_visible)),
        "script_srcs": scripts,
        "rendered": rendered is not None,
        "rendered_status": rendered.status if rendered else None,
        "rendered_url": rendered.url if rendered else None,
        "rendered_title": rendered.title if rendered else None,
        "date_range": date_range,
        "parsed_entries": parsed_entries,
        "parser_mode": parser_mode,
        "preview": preview,
        "export": export_meta,
        "export_preview": export_preview,
        "parse_error": parse_error,
        "body_sha256": hashlib.sha256(r.content).hexdigest()[:16],
        "raw_visible_start": raw_visible[:350],
        "rendered_lines_start": rendered_lines[:80],
        "rendered_lines_tail": rendered_lines[-40:] if rendered_lines else [],
    }



def _expand_full_list_open_page(page, wait_ms: int = 2200) -> bool:
    """Try the same full-list interaction that worked in the pre-0.2.6 collector."""
    candidates = [
        page.get_by_text("zobacz pełną listę", exact=False),
        page.locator("button", has_text="zobacz pełną listę"),
        page.locator("a", has_text="zobacz pełną listę"),
    ]
    for locator in candidates:
        try:
            count = locator.count()
        except Exception:
            count = 0
        for idx in range(count):
            el = locator.nth(idx)
            try:
                if not el.is_visible(timeout=400):
                    continue
                el.scroll_into_view_if_needed(timeout=900)
                el.click(timeout=1800)
                page.wait_for_timeout(wait_ms)
                # Trigger any lazy rows after expansion.
                for _ in range(8):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(250)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(250)
                return True
            except Exception:
                continue
    return False


def _download_csv_from_open_page(page, context, timeout_ms: int = 1800) -> tuple[list[dict], dict]:
    """Try the official CSV control using an already-open browser page.

    This intentionally has a very short timeout. Current collection should fail
    fast rather than launch a second Chromium instance and wait for minutes.
    """
    meta: dict = {"attempted": True}
    locator = page.get_by_text("CSV", exact=True)
    try:
        count = locator.count()
    except Exception:
        count = 0
    errors: list[str] = []
    for idx in range(count - 1, -1, -1):
        el = locator.nth(idx)
        try:
            if not el.is_visible(timeout=250):
                continue
        except Exception:
            continue
        try:
            el.scroll_into_view_if_needed(timeout=500)
        except Exception:
            pass
        try:
            href = el.evaluate("el => el.href || el.closest('a')?.href || ''")
            if href and not str(href).lower().startswith(("javascript:", "#")):
                resp = context.request.get(str(href), timeout=timeout_ms)
                if resp.ok:
                    content = resp.body()
                    entries = _parse_export_csv(content)
                    meta.update({"via": "href", "url": str(href), "bytes": len(content), "parsed_entries": len(entries)})
                    return entries, meta
        except Exception as exc:
            errors.append(f"href:{type(exc).__name__}")
        try:
            with page.expect_download(timeout=timeout_ms) as info:
                el.click(timeout=min(timeout_ms, 1200))
            dl = info.value
            path = dl.path()
            if path:
                content = Path(path).read_bytes()
                entries = _parse_export_csv(content)
                meta.update({"via": "download", "filename": dl.suggested_filename, "bytes": len(content), "parsed_entries": len(entries)})
                return entries, meta
        except Exception as exc:
            errors.append(f"download:{type(exc).__name__}")
    meta["error"] = "; ".join(errors[-5:]) or "Nie znaleziono aktywnego eksportu CSV"
    return [], meta


def _wait_for_chart_ready(page, source: str, timeout_ms: int = 4500) -> int:
    """Wait until ZPAV's dynamic chart has at least the preview rows.

    The page shell arrives much earlier than the chart data. Parsing after a
    fixed 300 ms caused intermittent 0-row results. This bounded poll waits
    only for the actual chart body and still fails fast.
    """
    deadline = time.monotonic() + max(0.5, timeout_ms / 1000.0)
    last_count = 0
    while time.monotonic() < deadline:
        try:
            text = page.locator("body").inner_text(timeout=900)
            _parse_date_range(text)
            last_count = len(_parse_rendered_text(text, max_position=100))
            if last_count >= 10:
                return last_count
        except Exception:
            pass
        page.wait_for_timeout(180)
    return last_count


def _extract_open_page(page, context, source: str, export_timeout_ms: int = 10000) -> dict:
    """Read the currently selected OLiA/OLiS week from one open page."""
    _wait_for_chart_ready(page, source, timeout_ms=4200)
    _expand_full_list_open_page(page)
    text = page.locator("body").inner_text(timeout=1800)
    html = page.content()
    preview_error = None
    try:
        data = parse_olis_rendered(html, text, source)
    except Exception as exc:
        preview_error = f"{type(exc).__name__}: {exc}"
        start_date, end_date = _parse_date_range(text)
        data = {
            "source": source,
            "chart_date": end_date,
            "issue_key": f"{start_date}_{end_date}",
            "chart_size": 100,
            "entries": [],
            "parser_mode": "rendered_not_ready",
        }
    if len(data["entries"]) >= 50:
        data["source_url"] = page.url
        data["parser_mode"] = data.get("parser_mode") or "rendered"
        return data

    export_entries, meta = _download_csv_from_open_page(page, context, timeout_ms=export_timeout_ms)
    if len(export_entries) >= 50:
        data["entries"] = export_entries
        data["parser_mode"] = "official_csv_same_session"
        data["export_meta"] = meta
        data["source_url"] = page.url
        return data
    detail = meta.get("error") or f"CSV: {len(export_entries)} pozycji"
    if preview_error:
        detail = f"podgląd: {preview_error}; eksport: {detail}"
    raise ValueError(
        f"Parser {source} odczytał tylko {len(data['entries'])} pozycji; "
        f"pełny eksport nie był gotowy ({detail}). Spróbuj ponownie."
    )


def _open_chart_browser(source: str, timeout_ms: int = 8000):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Brak Playwright/Chromium w obrazie") from exc

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    context = browser.new_context(
        locale="pl-PL",
        accept_downloads=True,
        viewport={"width": 1440, "height": 1000},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    page.set_default_timeout(1500)
    try:
        page.goto(URLS[source.upper()], wait_until="domcontentloaded", timeout=timeout_ms)
        _wait_for_chart_ready(page, source, timeout_ms=4200)
    except Exception:
        context.close(); browser.close(); pw.stop()
        raise
    return pw, browser, context, page


def _go_previous_week(page, old_range: str, timeout_ms: int = 2200) -> bool:
    """Click the chart's left-arrow control and wait briefly for a date change."""
    candidates = [
        page.get_by_text("<", exact=True),
        page.locator("button", has_text="<"),
        page.locator("a", has_text="<"),
    ]
    clicked = False
    for locator in candidates:
        try:
            count = locator.count()
        except Exception:
            count = 0
        for i in range(count):
            el = locator.nth(i)
            try:
                if not el.is_visible(timeout=150):
                    continue
                el.click(timeout=700)
                clicked = True
                break
            except Exception:
                continue
        if clicked:
            break
    if not clicked:
        return False

    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        page.wait_for_timeout(120)
        try:
            text = page.locator("body").inner_text(timeout=600)
            start, end = _parse_date_range(text)
            now = f"{start}_{end}"
            if now != old_range:
                page.wait_for_timeout(350)
                return True
        except Exception:
            pass
    return False


def iter_olis_history(source: str, count: int = 12):
    """Yield historical OLiA/OLiS weeks using one Chromium session.

    The official site keeps archive navigation on one URL, so the browser must
    click the previous-week control. Each week is fail-fast: a failed CSV export
    is yielded as an error and the walker continues when the date control works.
    """
    source = source.upper()
    if source not in URLS:
        raise ValueError(f"Nieznane źródło: {source}")
    count = max(1, min(int(count), 104))
    pw, browser, context, page = _open_chart_browser(source, timeout_ms=8000)
    try:
        for idx in range(count):
            old_range = ""
            try:
                text = page.locator("body").inner_text(timeout=1200)
                start, end = _parse_date_range(text)
                old_range = f"{start}_{end}"
                data = _extract_open_page(page, context, source, export_timeout_ms=10000)
                yield idx + 1, count, data, None
            except Exception as exc:
                yield idx + 1, count, None, f"{type(exc).__name__}: {exc}"
            if idx + 1 >= count:
                break
            if not old_range:
                try:
                    text = page.locator("body").inner_text(timeout=700)
                    start, end = _parse_date_range(text)
                    old_range = f"{start}_{end}"
                except Exception:
                    break
            if not _go_previous_week(page, old_range):
                break
    finally:
        try: context.close()
        except Exception: pass
        try: browser.close()
        except Exception: pass
        try: pw.stop()
        except Exception: pass


def fetch_olis(source: str, timeout: int = 45) -> dict:
    """Current OLiA/OLiS collector using the older, proven interaction path.

    0.2.6/0.2.7 shortened Chromium settling too aggressively and switched to
    same-session export, which produced the reproducible 12-row/CSV timeout.
    This restores the 0.1.9 strategy: settle, click full list, auto-scroll; OLiA
    additionally falls back to a separate official CSV export session.
    """
    source = source.upper()
    if source not in URLS:
        raise ValueError(f"Nieznane źródło: {source}")
    rendered = _render(source)
    data = parse_olis_rendered(rendered.html, rendered.text, source)
    if len(data["entries"]) < 50 and source == "OLIA":
        export_entries, export_meta = _try_official_export(source, timeout_ms=30000)
        if len(export_entries) >= 50:
            data["entries"] = export_entries
            data["parser_mode"] = "official_csv_export_legacy"
            data["export_meta"] = export_meta
    if len(data["entries"]) < 50:
        raise ValueError(
            f"Parser {source} odczytał tylko {len(data['entries'])} pozycji; "
            "pełna lista nie została pobrana"
        )
    data["source_url"] = rendered.url
    return data

