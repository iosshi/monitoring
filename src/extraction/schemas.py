from decimal import Decimal
from pydantic import BaseModel, Field, HttpUrl
from enum import Enum


class AnalysisStatus(str, Enum):
    INITIALIZED = "initialized"
    SIGNIFICANT = "significant"
    INSIGNIFICANT = "insignificant"
    UNCERTAIN = "uncertain"



class CompetitorOffer(BaseModel):
    source_url: HttpUrl
    product_name: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None

    discount: str | None = None
    availability: str | None = None

    delivery_conditions: str | None = None
    payment_conditions: str | None = None
    warranty_conditions: str | None = None

class OfferChange(BaseModel):
    field: str
    old_value: str | None = None
    new_value: str | None = None
    explanation: str


class AnalysisResult(BaseModel):
    status: AnalysisStatus
    current_snapshot: CompetitorOffer | None = None
    changes: list[OfferChange] = Field(default_factory=list)
    explanation: str

class AnalysisRequest(BaseModel):
    source_url: HttpUrl

    product_description: str
    page_title: str = ""
    page_text: str = Field(min_length=1)

    previous_snapshot: CompetitorOffer | None = None
    significance_criteria: list[str] = Field(min_length=1)
