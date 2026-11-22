from src.pipeline import run_pipeline
from decimal import Decimal
from src.extraction.schemas import AnalysisRequest, CompetitorOffer
from src.extraction.llm_client import GroqClient

url = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"

parsed_data = run_pipeline(url)

request = AnalysisRequest(
    source_url=url,
    product_description="Книга A Light in the Attic",
    page_title=parsed_data["title"],
    page_text=parsed_data["text"],
    previous_snapshot=CompetitorOffer(
    source_url=url,
    product_name="A Light in the Attic",
    price=Decimal("55.00"),
    currency="GBP",
    availability="In stock",
    ),  
    significance_criteria=[
    "Снижение или увеличение цены минимум на 5% считается значимым",
    "Изменение наличия товара считается значимым",
    ],
)

llm = GroqClient()
result = llm.analyze(request)

print(result.model_dump_json(indent=2))