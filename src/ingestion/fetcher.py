from src.ingestion.browser_fetcher import fetch_page_browser


def fetch_page(url: str) -> str:
    return fetch_page_browser(url)