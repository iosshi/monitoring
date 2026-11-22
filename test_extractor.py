from src.extraction.extractor import extract_offer


offer = extract_offer(
    source_url="https://example.com/product",
    extracted_data={
        "product_name": "Test product",
        "price": "1299.99",
        "currency": "RUB",
        "discount": "10%",
        "delivery_conditions": "Delivery in 2 days",
    },
)

print(offer)
print(offer.model_dump())