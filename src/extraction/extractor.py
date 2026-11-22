from src.extraction.schemas import CompetitorOffer

def extract_offer(source_url, extracted_data) -> CompetitorOffer:
    data = {
        "source_url":source_url,
        **extracted_data
    }
    return CompetitorOffer.model_validate(data)