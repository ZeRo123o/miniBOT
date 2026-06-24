from datetime import date
from decimal import Decimal

from langgraph.prebuilt.tool_node import ToolRuntime

from app.agents.toolkits.external.exchange_rate.client import ExchangeRateClient
from app.agents.toolkits.external.exchange_rate.schemas import ExchangeRateInput
from app.agents.toolkits.governance import fail_tool_call, finish_tool_call, start_tool_call
from app.agents.toolkits.registry import tool


@tool(
    category="external",
    tags=["finance", "exchange-rate"],
    display_name="汇率换算",
    config_guide="在扩展管理中启用后即可使用；返回参考汇率，不代表银行实时成交价。",
    description="""
查询两种货币之间的参考汇率，并换算指定金额。

适用于用户询问货币换算、汇率比较，或指定日期的历史参考汇率。from_currency 和
to_currency 必须是 ISO 4217 三位货币代码，例如 USD、CNY、EUR；amount 必须大于 0。
返回值是参考汇率与换算结果，不代表银行、支付机构或交易平台的实时成交报价。
""",
    args_schema=ExchangeRateInput,
)
async def exchange_rate(
    from_currency: str,
    to_currency: str,
    amount: Decimal = Decimal("1"),
    rate_date: date | None = None,
    runtime: ToolRuntime = None,
) -> dict:
    """Look up a reference exchange rate and convert one currency amount."""
    event = start_tool_call(
        runtime.context if runtime else None,
        tool_name="exchange_rate",
        payload={"from_currency": from_currency, "to_currency": to_currency, "amount": float(amount)},
    )
    try:
        if from_currency == to_currency:
            rate, resolved_date = Decimal("1"), rate_date.isoformat() if rate_date else ""
        else:
            rate, resolved_date = await ExchangeRateClient().get_rate(
                from_currency=from_currency,
                to_currency=to_currency,
                rate_date=rate_date,
            )
        converted_amount = amount * rate
        result = {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "amount": str(amount),
            "rate": str(rate),
            "converted_amount": str(converted_amount),
            "rate_date": resolved_date or None,
            "is_reference_rate": True,
        }
        finish_tool_call(event, rate_date=resolved_date or None)
        return result
    except Exception as error:  # noqa: BLE001
        fail_tool_call(event, error)
        return {"error": "exchange_rate_unavailable", "detail": str(error)}
