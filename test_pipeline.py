from src.pipeline import run_pipeline


result = run_pipeline(
    "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
)

print("URL:", result["source_url"])
print("Title:", result["title"])
print("Text:", result["text"][:500])