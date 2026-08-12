import asyncio

from nautilus_trader.adapters.kabu_station.config import KabuStationDataClientConfig
from nautilus_trader.adapters.kabu_station.constants import KABU, KABU_VENUE, MAX_REGISTERED_SYMBOLS
from nautilus_trader.adapters.kabu_station.http.client import KabuStationHttpClient
from nautilus_trader.adapters.kabu_station.parsing import BoardState, extract_ticks
from nautilus_trader.adapters.kabu_station.websocket.client import KabuStationWebSocketClient
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.data.messages import SubscribeQuoteTicks, SubscribeTradeTicks, UnsubscribeQuoteTicks, UnsubscribeTradeTicks
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.model.identifiers import ClientId, InstrumentId


class KabuStationDataClient(LiveMarketDataClient):
    """
    kabu STATION PUSH 配信 (板全量 -> 差分ティック) のデータクライアント。

    登録上限 50 銘柄 (REST/PUSH 共通)。履歴 API は存在しないため request 系は
    非対応 (履歴は jQuants アダプターが担う)。
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client: KabuStationHttpClient,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        instrument_provider: InstrumentProvider,
        config: KabuStationDataClientConfig,
        ws_url: str,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=ClientId(KABU),
            venue=KABU_VENUE,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
            config=config,
        )
        self._client = client
        self._exchange = config.exchange
        self._states: dict[str, BoardState] = {}
        self._subscribed: set[str] = set()
        self._ws = KabuStationWebSocketClient(
            url=ws_url,
            handler=self._on_push,
            on_reconnect=self._reregister,
        )

    async def _connect(self) -> None:
        await self._client.get_token()
        await self._instrument_provider.initialize()
        for instrument in self._instrument_provider.get_all().values():
            self._handle_data(instrument)
        self._ws.start(self._loop)

    async def _disconnect(self) -> None:
        await self._ws.stop()
        if self._subscribed:
            try:
                await self._client.unregister_symbols(sorted(self._subscribed), self._exchange)
            except Exception as e:
                self._log.warning(f"unregister on disconnect failed: {e}")
        await self._client.aclose()

    def _on_push(self, board: dict) -> None:
        symbol = board.get("Symbol")
        if symbol not in self._subscribed:
            return
        instrument_id = InstrumentId.from_str(f"{symbol}.{KABU_VENUE}")
        state = self._states.setdefault(symbol, BoardState())
        for tick in extract_ticks(board, state, instrument_id, self._clock.timestamp_ns()):
            self._handle_data(tick)

    def _reregister(self) -> None:
        if self._subscribed:
            self._loop.create_task(
                self._client.register_symbols(sorted(self._subscribed), self._exchange),
            )

    async def _register(self, instrument_id: InstrumentId) -> None:
        symbol = instrument_id.symbol.value
        if symbol in self._subscribed:
            return
        if len(self._subscribed) >= MAX_REGISTERED_SYMBOLS:
            self._log.error(
                f"Cannot subscribe {instrument_id}: kabusapi registration limit "
                f"({MAX_REGISTERED_SYMBOLS} symbols) reached",
            )
            return
        await self._client.register_symbols([symbol], self._exchange)
        self._subscribed.add(symbol)

    async def _unregister(self, instrument_id: InstrumentId) -> None:
        symbol = instrument_id.symbol.value
        if symbol not in self._subscribed:
            return
        self._subscribed.discard(symbol)
        self._states.pop(symbol, None)
        await self._client.unregister_symbols([symbol], self._exchange)

    async def _subscribe_quote_ticks(self, command: SubscribeQuoteTicks) -> None:
        await self._register(command.instrument_id)

    async def _subscribe_trade_ticks(self, command: SubscribeTradeTicks) -> None:
        await self._register(command.instrument_id)

    async def _unsubscribe_quote_ticks(self, command: UnsubscribeQuoteTicks) -> None:
        await self._unregister(command.instrument_id)

    async def _unsubscribe_trade_ticks(self, command: UnsubscribeTradeTicks) -> None:
        await self._unregister(command.instrument_id)
