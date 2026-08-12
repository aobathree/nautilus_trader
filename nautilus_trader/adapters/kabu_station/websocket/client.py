import asyncio
import json
from collections.abc import Callable

import websockets


class KabuStationWebSocketClient:
    """
    PUSH 配信 (board 全量、間引き 400ms) の受信。認証ヘッダ・送信メッセージは不要。

    切断時は指数バックオフで再接続し、`on_reconnect` (登録銘柄の再 /register 用)
    を呼ぶ。
    """

    def __init__(
        self,
        url: str,
        handler: Callable[[dict], None],
        on_reconnect: Callable[[], None] | None = None,
        max_backoff_secs: float = 60.0,
    ) -> None:
        self._url = url
        self._handler = handler
        self._on_reconnect = on_reconnect
        self._max_backoff = max_backoff_secs
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._running = True
        self._task = loop.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        first = True
        backoff = 1.0
        while self._running:
            try:
                async with websockets.connect(self._url) as ws:
                    if not first and self._on_reconnect:
                        self._on_reconnect()
                    first = False
                    backoff = 1.0
                    async for message in ws:
                        self._handler(json.loads(message))
            except asyncio.CancelledError:
                raise
            except Exception:
                if not self._running:
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff)
