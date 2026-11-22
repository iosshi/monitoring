from src.extraction.schemas import AnalysisRequest
from src.extraction.prompts import build_messages
from src.pipeline import run_pipeline

url = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"

parsed_data = run_pipeline(url)

request = AnalysisRequest(
    source_url=url,
    product_description="Книга A Light in the Attic",
    page_title=parsed_data["title"],
    page_text=parsed_data["text"],
    previous_snapshot=None,
    significance_criteria=[
        "Изменение цены минимум на 100 рублей или 5%",
        "Изменение наличия товара",
        "Появление или исчезновение акции",
    ],
)

messages = build_messages(request)

for message in messages:
    print(f"\n--- {message['role'].upper()} ---")
    print(message["content"][:1500])