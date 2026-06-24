from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class ExchangeRateInput(BaseModel):
    """A single reference-rate lookup or currency conversion request."""

    from_currency: str = Field(description="ISO 4217 source currency code, for example USD")
    to_currency: str = Field(description="ISO 4217 target currency code, for example CNY")
    amount: Decimal = Field(default=Decimal("1"), gt=0, description="Amount to convert")
    rate_date: date | None = Field(default=None, description="Optional historical rate date (YYYY-MM-DD)")

    @field_validator("from_currency", "to_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a three-letter ISO 4217 code")
        return normalized
