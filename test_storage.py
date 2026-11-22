
from src.pipeline import run_pipeline


url = "https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html"

result = run_pipeline(
    url=url,
    product_description="Книга A Light in the Attic",
    significance_criteria=[
        "Снижение или увеличение цены минимум на 5% считается значимым",
        "Изменение наличия товара считается значимым",
    ],
)

print(result.model_dump_json(indent=2))
