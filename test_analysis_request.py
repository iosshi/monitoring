from src.pipeline import run_pipeline
from src.extraction.schemas import AnalysisRequest

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

print(request.model_dump_json(indent=2))