import asyncio
import time
from urllib.parse import urlparse

import httpx

from nautilus_trader.adapters.kabu_station.http.errors import KabuStationApiError


class RateGate:
    """Simple async rate limiter: max `rate` requests per second."""

    def __init__(self, rate: int) -> None:
        self._min_interval = 1.0 / rate
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


class KabuStationHttpClient:
    """
    kabusapi REST client with token management.

    - POST /token {APIPassword} -> Token を X-API-KEY ヘッダで送付
    - 401 は GET のみトークン再発行 + 1回リトライ (発注系は再送しない —
      結果不明時は /orders 照会が先)
    - レート制限: 発注系 5 req/s、情報系 10 req/s (公式 FAQ 値)
    - HTTP 200 でも Result != 0 はエラー
    """

    ORDER_PATHS = ("/sendorder", "/cancelorder")

    def __init__(
        self,
        api_password: str,
        base_url: str = "http://localhost:18081/kabusapi",
        allow_remote: bool = False,
        timeout_secs: float = 30.0,
    ) -> None:
        if not api_password:
            raise ValueError(
                "kabu STATION API password is empty (set env var KABU_STATION_API_PASSWORD)",
            )
        host = urlparse(base_url).hostname
        if not allow_remote and host not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError(f"Remote base_url refused: {base_url} (set allow_remote=True)")
        self._api_password = api_password
        self._token: str | None = None
        self._token_lock = asyncio.Lock()
        self._order_gate = RateGate(5)
        self._info_gate = RateGate(10)
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_secs)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_token(self, force_refresh: bool = False) -> str:
        async with self._token_lock:
            if self._token and not force_refresh:
                return self._token
            resp = await self._client.post("/token", json={"APIPassword": self._api_password})
            payload = self._parse(resp)
            token = payload.get("Token")
            if not token:
                raise KabuStationApiError(-1, "token missing in /token response")
            self._token = token
            return token

    @staticmethod
    def _parse(resp: httpx.Response) -> dict:
        if resp.status_code >= 400:
            try:
                body = resp.json()
                raise KabuStationApiError(
                    int(body.get("Code", -1)),
                    str(body.get("Message", resp.text[:200])),
                    resp.status_code,
                )
            except (ValueError, KeyError, TypeError):
                raise KabuStationApiError(-1, resp.text[:200], resp.status_code)
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("Result", 0) != 0:
            raise KabuStationApiError(
                int(payload.get("Code", payload["Result"])),
                str(payload.get("Message", "Result != 0")),
                resp.status_code,
            )
        return payload

    async def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json: dict | None = None,
    ) -> dict | list:
        is_order = any(path.startswith(p) for p in self.ORDER_PATHS)
        gate = self._order_gate if is_order else self._info_gate
        retry_auth = method.upper() == "GET"
        token = await self.get_token()
        for attempt in (0, 1):
            await gate.acquire()
            resp = await self._client.request(
                method,
                path,
                params=params,
                json=json,
                headers={"X-API-KEY": token},
            )
            if resp.status_code == 401 and retry_auth and attempt == 0:
                token = await self.get_token(force_refresh=True)
                continue
            return self._parse(resp)
        raise KabuStationApiError(-1, "unreachable")  # pragma: no cover

    # --- endpoints ---

    async def send_order(self, payload: dict) -> str:
        # OpenAPI v1.5: /sendorder に Password フィールドは存在しない (旧仕様で廃止)
        result = await self.request("POST", "/sendorder", json=payload)
        return str(result["OrderId"])

    async def cancel_order(self, order_id: str) -> None:
        await self.request("PUT", "/cancelorder", json={"OrderId": order_id})

    async def get_orders(self, updtime: str | None = None) -> list:
        params: dict = {"product": 0, "details": "true"}
        if updtime:
            params["updtime"] = updtime
        result = await self.request("GET", "/orders", params=params)
        return result if isinstance(result, list) else []

    async def get_positions(self) -> list:
        result = await self.request("GET", "/positions", params={"product": 0})
        return result if isinstance(result, list) else []

    async def get_wallet_cash(self) -> dict:
        return await self.request("GET", "/wallet/cash")  # type: ignore[return-value]

    async def get_wallet_margin(self) -> dict:
        return await self.request("GET", "/wallet/margin")  # type: ignore[return-value]

    async def get_board(self, symbol: str, exchange: int = 1) -> dict:
        return await self.request("GET", f"/board/{symbol}@{exchange}")  # type: ignore[return-value]

    async def get_soft_limit(self) -> dict:
        return await self.request("GET", "/apisoftlimit")  # type: ignore[return-value]

    async def register_symbols(self, symbols: list[str], exchange: int = 1) -> None:
        await self.request(
            "PUT",
            "/register",
            json={"Symbols": [{"Symbol": s, "Exchange": exchange} for s in symbols]},
        )

    async def unregister_symbols(self, symbols: list[str], exchange: int = 1) -> None:
        await self.request(
            "PUT",
            "/unregister",
            json={"Symbols": [{"Symbol": s, "Exchange": exchange} for s in symbols]},
        )
