import asyncio
import datetime as dt
import time
from collections.abc import AsyncIterator

import httpx

from nautilus_trader.adapters.jquants.constants import JQUANTS_BASE_URL
from nautilus_trader.adapters.jquants.http.errors import JQuantsError


def _fmt(d: dt.date | None) -> str | None:
    return d.strftime("%Y%m%d") if d is not None else None


class JQuantsHttpClient:
    """
    Async client for the J-Quants API V2 (static ``x-api-key`` auth).

    All endpoints share the ``{"data": [...], "pagination_key": ...}`` response
    shape, absorbed here by `paginate`. Retries 429/5xx/timeouts with
    exponential backoff (2**attempt seconds); 4xx raise immediately.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = JQUANTS_BASE_URL,
        request_interval_ms: int = 300,
        timeout_secs: float = 120.0,
        max_retries: int = 6,
    ) -> None:
        if not api_key:
            raise ValueError("J-Quants API key is empty (set env var JQUANTS_API_KEY)")
        self._interval = request_interval_ms / 1000.0
        self._max_retries = max_retries
        self._last_request = 0.0
        self._throttle = asyncio.Lock()
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"x-api-key": api_key},
            timeout=timeout_secs,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict) -> dict:
        for attempt in range(self._max_retries + 1):
            async with self._throttle:
                wait = self._interval - (time.monotonic() - self._last_request)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_request = time.monotonic()
            try:
                resp = await self._client.get(path, params=params)
            except httpx.TimeoutException:
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                raise JQuantsError(0, f"timeout after {self._max_retries} retries: {path}")
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
            raise JQuantsError(resp.status_code, resp.text[:500])
        raise JQuantsError(0, f"retries exhausted: {path}")  # pragma: no cover

    async def paginate(self, path: str, params: dict) -> AsyncIterator[dict]:
        params = {k: v for k, v in params.items() if v is not None}
        pagination_key: str | None = None
        while True:
            page = dict(params)
            if pagination_key:
                page["pagination_key"] = pagination_key
            payload = await self._get(path, page)
            for row in payload.get("data", []):
                yield row
            pagination_key = payload.get("pagination_key")
            if not pagination_key:
                return

    def get_daily_bars(
        self,
        code: str | None = None,
        date: dt.date | None = None,
        from_: dt.date | None = None,
        to: dt.date | None = None,
    ) -> AsyncIterator[dict]:
        if (code is None) == (date is None):
            raise ValueError("exactly one of `code` or `date` is required")
        return self.paginate(
            "/v2/equities/bars/daily",
            {"code": code, "date": _fmt(date), "from": _fmt(from_), "to": _fmt(to)},
        )

    def get_listed(self, date: dt.date | None = None) -> AsyncIterator[dict]:
        return self.paginate("/v2/equities/master", {"date": _fmt(date)})

    def get_fin_summary(
        self,
        code: str | None = None,
        date: dt.date | None = None,
    ) -> AsyncIterator[dict]:
        if (code is None) == (date is None):
            raise ValueError("exactly one of `code` or `date` is required")
        return self.paginate("/v2/fins/summary", {"code": code, "date": _fmt(date)})

    def get_calendar(self, from_: dt.date, to: dt.date) -> AsyncIterator[dict]:
        return self.paginate("/v2/markets/calendar", {"from": _fmt(from_), "to": _fmt(to)})
