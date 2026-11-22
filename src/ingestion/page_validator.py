import re

from bs4 import BeautifulSoup


BLOCKED_MARKERS = [
    "just a moment",
    "verify you are human",
    "checking your browser",
    "access denied",
    "captcha",
    "unusual traffic",
    "temporarily blocked",
]

JS_APP_MARKERS = [
    "enable javascript",
    "javascript is required",
    "please enable javascript",
]


def validate_page(html: str) -> tuple[bool, str | None]:
    if not html or not html.strip():
        return False, "Empty HTML"

    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(" ", strip=True) if soup.title else ""

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).lower()

    page_content = f"{title.lower()} {text}"

    for marker in BLOCKED_MARKERS:
        if marker in page_content:
            return False, f"Blocked page: {marker}"

    for marker in JS_APP_MARKERS:
        if marker in page_content:
            return False, f"JavaScript content required: {marker}"

    if len(text) < 100:
        return False, "Too little visible page content"

    return True, None