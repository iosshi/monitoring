
from src.pipeline import run_pipeline
from src.product_config import load_products
import traceback
from concurrent.futures import ThreadPoolExecutor

def _run_product(product: dict) -> dict:
    try:
        result = run_pipeline(
            url=product["url"],
            product_description=product["product_description"],
            significance_criteria=product["significance_criteria"],
        )
        return {
            "product": product["product_description"],
            "url": product["url"],
            "status": result.status.value,
            "changes": [change.model_dump() for change in result.changes],
            "explanation": result.explanation,
            "error": None,
        }
    except Exception as error:
        traceback.print_exc()
        return {
            "product": product["product_description"],
            "url": product["url"],
            "status": "error",
            "changes": [],
            "explanation": None,
            "error": f"{type(error).__name__}: {error}",
        }


def run_batch(max_workers: int = 10) -> dict:
    products = load_products()
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")
    # Preserve configuration order in the report while fetching products in
    # parallel. Ten workers match the KT2 sizing assumption.
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(_run_product, products))

    return {
        "total": len(products),
        "successful": sum(
            result["error"] is None for result in results
        ),
        "failed": sum(
            result["error"] is not None for result in results
        ),
        "results": results,
    }
