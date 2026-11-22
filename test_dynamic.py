import requests
from bs4 import BeautifulSoup

from src.ingestion.browser_fetcher import fetch_page_browser


url = "https://quotes.toscrape.com/js/"


# Обычный HTTP-запрос
session = requests.Session()
session.trust_env = False

response = session.get(url, timeout=30)
response.raise_for_status()

requests_html = response.text


# Загрузка через браузер
browser_html = fetch_page_browser(
    url,
    wait_selector=".quote",
)


# Считаем количество цитат
requests_soup = BeautifulSoup(requests_html, "html.parser")
browser_soup = BeautifulSoup(browser_html, "html.parser")

requests_quotes = requests_soup.select(".quote")
browser_quotes = browser_soup.select(".quote")


print("========== REQUESTS ==========")
print("HTML length:", len(requests_html))
print("Quotes found:", len(requests_quotes))

print("\n========== PLAYWRIGHT ==========")
print("HTML length:", len(browser_html))
print("Quotes found:", len(browser_quotes))

print("\n========== COMPARISON ==========")
print("Requests:", len(requests_quotes))
print("Playwright:", len(browser_quotes))