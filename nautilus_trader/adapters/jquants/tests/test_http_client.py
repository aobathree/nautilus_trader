import datetime as dt

import httpx
import pytest
import respx

from nautilus_trader.adapters.jquants.http.client import JQuantsHttpClient
from nautilus_trader.adapters.jquants.http.errors import JQuantsError


BASE = "https://api.jquants.com"


def make_client() -> JQuantsHttpClient:
    return JQuantsHttpClient(api_key="test-key", request_interval_ms=0, max_retries=2)


@pytest.mark.asyncio
@respx.mock
async def test_pagination_concatenates_pages():
    route = respx.get(f"{BASE}/v2/equities/bars/daily")
    route.side_effect = [
        httpx.Response(200, json={"data": [{"Date": "20260810"}], "pagination_key": "k1"}),
        httpx.Response(200, json={"data": [{"Date": "20260812"}]}),
    ]
    client = make_client()
    rows = [r async for r in client.get_daily_bars(code="83160")]
    assert [r["Date"] for r in rows] == ["20260810", "20260812"]
    assert "pagination_key=k1" in str(route.calls[1].request.url)
    assert route.calls[0].request.headers["x-api-key"] == "test-key"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_retry_on_429_then_success():
    route = respx.get(f"{BASE}/v2/equities/master")
    route.side_effect = [
        httpx.Response(429, text="rate limited"),
        httpx.Response(200, json={"data": [{"Code": "83160"}]}),
    ]
    client = make_client()
    rows = [r async for r in client.get_listed()]
    assert len(rows) == 1
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_400_raises_immediately():
    respx.get(f"{BASE}/v2/equities/bars/daily").mock(
        return_value=httpx.Response(400, text="subscription range"),
    )
    client = make_client()
    with pytest.raises(JQuantsError) as e:
        _ = [r async for r in client.get_daily_bars(code="83160", from_=dt.date(2000, 1, 1))]
    assert e.value.status == 400
    await client.aclose()


@pytest.mark.asyncio
async def test_code_and_date_are_mutually_exclusive():
    client = make_client()
    with pytest.raises(ValueError):
        client.get_daily_bars()
    with pytest.raises(ValueError):
        client.get_daily_bars(code="83160", date=dt.date(2026, 8, 12))
    with pytest.raises(ValueError):
        client.get_fin_summary()
    await client.aclose()


def test_empty_api_key_rejected():
    with pytest.raises(ValueError):
        JQuantsHttpClient(api_key="")
