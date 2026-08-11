from __future__ import annotations

from dataclasses import dataclass
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
    timeout_ms: int = 45000,
    settle_ms: int = 2500,
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
                    locator.wait_for(state="visible", timeout=7000)
                    locator.click(timeout=7000)
                    page.wait_for_timeout(1800)
                except Exception:
                    # Diagnostics/parser will reveal if a site's control changed.
                    pass

            if auto_scroll:
                last_height = 0
                stable = 0
                for _ in range(16):
                    height = int(page.evaluate("document.body.scrollHeight"))
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(500)
                    new_height = int(page.evaluate("document.body.scrollHeight"))
                    if new_height <= max(last_height, height):
                        stable += 1
                    else:
                        stable = 0
                    last_height = new_height
                    if stable >= 2:
                        break
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(250)

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
