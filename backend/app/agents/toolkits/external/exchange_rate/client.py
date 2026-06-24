from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import get_settings


class ExchangeRateClient:
    """Small HTTP client for the configured reference exchange-rate provider."""

    async def get_rate(
        self,
        *,
        from_currency: str,
        to_currency: str,
        rate_date: date | None,
    ) -> tuple[Decimal, str]:
        settings = get_settings()
        endpoint = rate_date.isoformat() if rate_date else "latest"
        async with httpx.AsyncClient(timeout=settings.exchange_rate_timeout_seconds) as client:
            response = await client.get(
                f"{settings.exchange_rate_base_url.rstrip('/')}/{endpoint}",
                params={"base": from_currency, "symbols": to_currency},
            )
            response.raise_for_status()
        return self._parse_rate(response.json(), to_currency)

    @staticmethod
    def _parse_rate(payload: dict[str, Any], to_currency: str) -> tuple[Decimal, str]:
        rates = payload.get("rates") or {}
        raw_rate = rates.get(to_currency)
        if raw_rate is None:
            raise ValueError(f"reference rate is unavailable for {to_currency}")
        rate = Decimal(str(raw_rate))
        if rate <= 0:
            raise ValueError("reference rate must be positive")
        return rate, str(payload.get("date") or "")
