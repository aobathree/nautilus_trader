import httpx
import pytest
import respx

from nautilus_trader.adapters.kabu_station.http.client import KabuStationHttpClient
from nautilus_trader.adapters.kabu_station.http.errors import KabuStationApiError


BASE = "http://localhost:18081/kabusapi"


def make_client(**kw) -> KabuStationHttpClient:
    return KabuStationHttpClient(api_password="apipw", **kw)


@pytest.mark.asyncio
@respx.mock
async def test_token_flow_and_header():
    respx.post(f"{BASE}/token").mock(
        return_value=httpx.Response(200, json={"ResultCode": 0, "Token": "tok1"}),
    )
    board = respx.get(f"{BASE}/board/7203@1").mock(
        return_value=httpx.Response(200, json={"Symbol": "7203"}),
    )
    client = make_client()
    result = await client.get_board("7203")
    assert result["Symbol"] == "7203"
    assert board.calls[0].request.headers["X-API-KEY"] == "tok1"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_401_on_get_refreshes_token_once():
    tokens = respx.post(f"{BASE}/token")
    tokens.side_effect = [
        httpx.Response(200, json={"Token": "old"}),
        httpx.Response(200, json={"Token": "new"}),
    ]
    board = respx.get(f"{BASE}/board/7203@1")
    board.side_effect = [
        httpx.Response(401, json={"Code": 4001007, "Message": "token expired"}),
        httpx.Response(200, json={"Symbol": "7203"}),
    ]
    client = make_client()
    result = await client.get_board("7203")
    assert result["Symbol"] == "7203"
    assert board.calls[1].request.headers["X-API-KEY"] == "new"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_401_on_order_is_not_retried():
    respx.post(f"{BASE}/token").mock(return_value=httpx.Response(200, json={"Token": "t"}))
    send = respx.post(f"{BASE}/sendorder").mock(
        return_value=httpx.Response(401, json={"Code": 4001007, "Message": "token expired"}),
    )
    client = make_client()
    with pytest.raises(KabuStationApiError):
        await client.send_order({"Symbol": "7203"})
    assert len(send.calls) == 1  # 発注系は自動再送しない
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_http_200_with_nonzero_result_raises():
    respx.post(f"{BASE}/token").mock(return_value=httpx.Response(200, json={"Token": "t"}))
    respx.post(f"{BASE}/sendorder").mock(
        return_value=httpx.Response(
            200,
            json={"Result": 1, "Code": 100, "Message": "rejected"},
        ),
    )
    client = make_client()
    with pytest.raises(KabuStationApiError) as e:
        await client.send_order({"Symbol": "7203"})
    assert e.value.code == 100
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_sendorder_returns_order_id_without_password_field():
    respx.post(f"{BASE}/token").mock(return_value=httpx.Response(200, json={"Token": "t"}))
    send = respx.post(f"{BASE}/sendorder").mock(
        return_value=httpx.Response(200, json={"Result": 0, "OrderId": "OID1"}),
    )
    client = make_client()
    order_id = await client.send_order({"Symbol": "7203"})
    assert order_id == "OID1"
    import json

    body = json.loads(send.calls[0].request.content)
    assert "Password" not in body  # OpenAPI v1.5: Password フィールドは存在しない
    await client.aclose()


def test_env_specific_api_password_resolution(monkeypatch):
    from types import SimpleNamespace

    from nautilus_trader.adapters.kabu_station.config import resolve_api_password

    monkeypatch.setenv("KABU_STATION_API_PASSWORD_PRACTICE", "pw-test")
    monkeypatch.setenv("KABU_STATION_API_PASSWORD_PRODUCTION", "pw-live")
    cfg = SimpleNamespace(api_password=None, environment="practice")
    assert resolve_api_password(cfg) == "pw-test"
    cfg = SimpleNamespace(api_password=None, environment="production")
    assert resolve_api_password(cfg) == "pw-live"
    # フォールバック
    monkeypatch.delenv("KABU_STATION_API_PASSWORD_PRODUCTION")
    monkeypatch.setenv("KABU_STATION_API_PASSWORD", "pw-common")
    assert resolve_api_password(cfg) == "pw-common"


def test_remote_base_url_refused():
    with pytest.raises(ValueError, match="Remote"):
        KabuStationHttpClient(api_password="x", base_url="http://192.168.1.5:18080/kabusapi")


def test_empty_api_password_rejected():
    with pytest.raises(ValueError):
        KabuStationHttpClient(api_password="")
