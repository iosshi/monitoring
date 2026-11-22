from src.ingestion.browser_fetcher import fetch_page_browser
from src.extraction.parser import parse_page


url = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"

html = fetch_page_browser(url)
parsed = parse_page(html)

print("HTML length:", len(html))
print("Title:", parsed["title"])
print("Text:", parsed["text"][:500])