from bs4 import BeautifulSoup

from src.ingestion.fetcher import fetch_page

url = "https://quotes.toscrape.com/js/"

html = fetch_page(url)

soup = BeautifulSoup(html, "html.parser")
quotes = soup.select(".quote")

print("HTML length:", len(html))
print("Quotes found:", len(quotes))