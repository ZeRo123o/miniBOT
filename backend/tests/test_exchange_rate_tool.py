from __future__ import annotations

from datetime import date
from decimal import Decimal
import unittest
from unittest.mock import AsyncMock, patch

from langgraph.prebuilt.tool_node import _get_all_injected_args

from app.agents.toolkits.external.exchange_rate.client import ExchangeRateClient
from app.agents.toolkits.external.exchange_rate.schemas import ExchangeRateInput
from app.agents.toolkits.external.exchange_rate.tools import exchange_rate


class ExchangeRateToolTests(unittest.IsolatedAsyncioTestCase):
    def test_runtime_is_injected_and_hidden_from_tool_schema(self):
        injected_args = _get_all_injected_args(exchange_rate)
        self.assertEqual(injected_args.runtime, "runtime")
        self.assertNotIn(
            "runtime",
            exchange_rate.tool_call_schema.model_json_schema()["properties"],
        )

    def test_schema_normalizes_iso_currency_codes(self):
        payload = ExchangeRateInput(from_currency=" usd ", to_currency="cny")
        self.assertEqual(payload.from_currency, "USD")
        self.assertEqual(payload.to_currency, "CNY")

    async def test_converts_with_reference_rate(self):
        with patch.object(
            ExchangeRateClient,
            "get_rate",
            new=AsyncMock(return_value=(Decimal("7.2"), "2026-06-24")),
        ):
            result = await exchange_rate.ainvoke(
                {"from_currency": "USD", "to_currency": "CNY", "amount": "10"}
            )
        self.assertEqual(result["converted_amount"], "72.0")
        self.assertTrue(result["is_reference_rate"])

    async def test_same_currency_does_not_call_provider(self):
        with patch.object(ExchangeRateClient, "get_rate", new=AsyncMock()) as get_rate:
            result = await exchange_rate.ainvoke(
                {
                    "from_currency": "CNY",
                    "to_currency": "CNY",
                    "amount": "10",
                    "rate_date": date(2026, 6, 1),
                }
            )
        get_rate.assert_not_awaited()
        self.assertEqual(result["rate"], "1")
