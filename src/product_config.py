
import json
from pathlib import Path


PRODUCTS_PATH = Path(__file__).resolve().parent.parent / "products.json"


def load_products() -> list[dict]:
    with open(PRODUCTS_PATH, encoding="utf-8") as file:
        products = json.load(file)

    for product in products:
        required_fields = {
            "url",
            "product_description",
            "significance_criteria",
        }

        if not required_fields.issubset(product):
            raise ValueError(f"Invalid product config: {product}")

    return products
