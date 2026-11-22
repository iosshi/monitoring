from src.extraction.schemas import (
    AnalysisResult,
    AnalysisStatus,
    CompetitorOffer,
    OfferChange,
)

offer = CompetitorOffer(
    source_url="https://example.com/product",
    product_name="Test product",
    price="1299.99",
    currency="RUB",
    availability="In stock",
)

result = AnalysisResult(
    status=AnalysisStatus.SIGNIFICANT,
    current_snapshot=offer,
    changes=[
        OfferChange(
            field="price",
            old_value="1399.99",
            new_value="1299.99",
            explanation="Price decreased by 100 RUB",
        )
    ],
    explanation="The price decreased significantly.",
)

print(result.model_dump_json(indent=2))