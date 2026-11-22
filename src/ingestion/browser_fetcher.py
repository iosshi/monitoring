from playwright.sync_api import sync_playwright


def fetch_page_browser(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            if response and response.status >= 400:
                raise RuntimeError(
                    f"Page returned HTTP {response.status}: {url}"
                )

            page.wait_for_timeout(2000)

            html = page.content()

            if not html.strip():
                raise RuntimeError(f"Empty page: {url}")

            return html

        finally:
            browser.close()