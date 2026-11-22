from decimal import Decimal

from src.pipeline import run_pipeline
from src.extraction.schemas import CompetitorOffer


url = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"

previous_snapshot = CompetitorOffer(
    source_url=url,
    product_name="A Light in the Attic",
    price=Decimal("55.00"),
    currency="GBP",
    availability="In stock",
)

result = run_pipeline(
    url=url,
    product_description="Книга A Light in the Attic",
    significance_criteria=[
        "Снижение или увеличение цены на 5% и более считается значимым.",
        "Изменение наличия товара считается значимым.",
    ],
    previous_snapshot_override=previous_snapshot,
)

print(result.model_dump_json(indent=2))