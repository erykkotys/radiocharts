from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RenderedPage:
    url: str
    status: int | None
    html: str
    text: str
    title: str


def render_page(url: str, timeout_ms: int = 45000, settle_ms: int = 3000) -> RenderedPage:
    """Render a JavaScript-driven public page with Chromium.

    OLiA/OLiS return only the application shell to ordinary HTTP clients and
    load the actual chart in JavaScript.  Playwright gives us the same DOM a
    browser sees.  Chromium is installed in the Docker image.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # makes diagnostics clearer outside Docker
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
            # The chart is fetched after DOMContentLoaded.  Network-idle is not
            # reliable on ad/analytics-heavy sites, so use a short settle time
            # and wait for chart-specific visible text where possible.
            page.wait_for_timeout(settle_ms)
            try:
                page.get_by_text("pozycja", exact=False).first.wait_for(timeout=8000)
            except Exception:
                pass
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
