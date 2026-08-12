from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class RenderedPage:
    url: str
    status: int | None
    html: str
    text: str
    title: str


def render_page(
    url: str,
    timeout_ms: int = 12000,
    settle_ms: int = 800,
    click_texts: Iterable[str] | None = None,
    auto_scroll: bool = False,
) -> RenderedPage:
    """Render a JavaScript-driven public page with Chromium.

    ``click_texts`` is useful for sites that initially expose only a preview
    (OLiA/OLiS use a ``zobacz pełną listę`` control). ``auto_scroll`` triggers
    lazy-loaded rows without relying on network-idle, which is unreliable on
    ad/analytics-heavy pages.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Brak Playwright/Chromium w obrazie") from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            page = browser.new_page(
                locale="pl-PL",
                viewport={"width": 1440, "height": 1200},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(settle_ms)

            for label in click_texts or []:
                try:
                    locator = page.get_by_text(label, exact=False).first
                    locator.wait_for(state="visible", timeout=2500)
                    locator.click(timeout=2500)
                    page.wait_for_timeout(700)
                except Exception:
                    # Diagnostics/parser will reveal if a site's control changed.
                    pass

            if auto_scroll:
                last_height = 0
                stable = 0
                for _ in range(8):
                    height = int(page.evaluate("document.body.scrollHeight"))
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(120)
                    new_height = int(page.evaluate("document.body.scrollHeight"))
                    if new_height <= max(last_height, height):
                        stable += 1
                    else:
                        stable = 0
                    last_height = new_height
                    if stable >= 2:
                        break
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(120)

            html = page.content()
            text = page.locator("body").inner_text(timeout=10000)
            title = page.title()
            return RenderedPage(
                url=page.url,
                status=response.status if response else None,
                html=html,
                text=text,
                title=title,
            )
        finally:
            browser.close()


@dataclass
class DownloadedFile:
    url: str
    filename: str
    content: bytes
    via: str


def download_by_text(
    url: str,
    labels: Iterable[str] = ("CSV",),
    timeout_ms: int = 12000,
    settle_ms: int = 800,
) -> DownloadedFile:
    """Download a public export exposed by a text link/button.

    First waits for a normal browser download. If the control is a direct
    anchor instead, uses Playwright's request context so cookies/session are
    preserved. This is useful for OLiA/OLiS official CSV/JSON export controls.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Brak Playwright/Chromium w obrazie") from exc

    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(
            locale="pl-PL",
            accept_downloads=True,
            viewport={"width": 1440, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(settle_ms)
            for label in labels:
                locators = [
                    page.get_by_text(label, exact=True),
                    page.locator("a", has_text=label),
                    page.locator("button", has_text=label),
                ]
                for locator in locators:
                    try:
                        count = locator.count()
                    except Exception:
                        count = 0
                    for idx in range(max(0, count - 1), -1, -1):
                        el = locator.nth(idx)
                        try:
                            el.scroll_into_view_if_needed(timeout=3000)
                        except Exception:
                            pass
                        # Prefer a direct export href when the page exposes one.
                        try:
                            href = el.evaluate("el => el.href || el.closest('a')?.href || ''")
                            if href and not str(href).lower().startswith(("javascript:", "#")):
                                resp = context.request.get(href, timeout=timeout_ms)
                                if resp.ok:
                                    content = resp.body()
                                    if content:
                                        name = str(href).split("?")[0].rstrip("/").split("/")[-1] or f"export.{label.lower()}"
                                        return DownloadedFile(str(href), name, content, "href")
                        except Exception as exc:
                            errors.append(f"{label}/href: {type(exc).__name__}")
                        # Otherwise handle JavaScript-triggered browser download.
                        try:
                            with page.expect_download(timeout=3500) as info:
                                el.click(timeout=3000)
                            dl = info.value
                            path = dl.path()
                            if path:
                                content = Path(path).read_bytes()
                                if content:
                                    return DownloadedFile(page.url, dl.suggested_filename or f"export.{label.lower()}", content, "download")
                        except Exception as exc:
                            errors.append(f"{label}/download: {type(exc).__name__}")
            raise ValueError("Nie udało się pobrać eksportu: " + "; ".join(errors[-8:]))
        finally:
            context.close()
            browser.close()
