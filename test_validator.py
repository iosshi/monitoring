
from src.ingestion.fetcher import fetch_page
from src.ingestion.page_validator import validate_page

urls = [
    "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
    "https://quotes.toscrape.com/js/",
]

for url in urls:
    html = fetch_page(url)
    reason = validate_page(html)

    print(f"\nURL: {url}")
    print("Valid:", reason is None)
    print("Reason:", reason)
