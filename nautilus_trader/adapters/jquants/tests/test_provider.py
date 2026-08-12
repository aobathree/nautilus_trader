import httpx
import pytest
import respx

from nautilus_trader.adapters.jquants.http.client import JQuantsHttpClient
from nautilus_trader.adapters.jquants.providers import JQuantsInstrumentProvider
from nautilus_trader.model.identifiers import InstrumentId


MASTER = {
    "data": [
        {"Code": "83160", "CoName": "三井住友FG", "MktNm": "プライム"},
        {"Code": "72030", "CoName": "トヨタ自動車", "MktNm": "プライム"},
        {"Code": "130A0", "CoName": "ベリタス", "MktNm": "グロース"},
    ],
}


@pytest.mark.asyncio
@respx.mock
async def test_load_all_async():
    respx.get("https://api.jquants.com/v2/equities/master").mock(
        return_value=httpx.Response(200, json=MASTER),
    )
    client = JQuantsHttpClient(api_key="k", request_interval_ms=0)
    provider = JQuantsInstrumentProvider(client)
    await provider.load_all_async()
    assert provider.count == 3
    assert provider.find(InstrumentId.from_str("7203.XTKS")) is not None
    assert provider.find(InstrumentId.from_str("130A.XTKS")) is not None
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_load_ids_async_filters():
    respx.get("https://api.jquants.com/v2/equities/master").mock(
        return_value=httpx.Response(200, json=MASTER),
    )
    client = JQuantsHttpClient(api_key="k", request_interval_ms=0)
    provider = JQuantsInstrumentProvider(client)
    await provider.load_ids_async([InstrumentId.from_str("8316.XTKS")])
    assert provider.count == 1
    await client.aclose()
