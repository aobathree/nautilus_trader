import asyncio

from nautilus_trader.adapters.jquants.config import JQuantsDataClientConfig
from nautilus_trader.adapters.jquants.constants import JQUANTS, JQUANTS_VENUE
from nautilus_trader.adapters.jquants.http.client import JQuantsHttpClient
from nautilus_trader.adapters.jquants.parsing import (
    from_ticker,
    make_bar,
    parse_daily_bar_row,
    parse_equity,
    suffix_factors,
)
from nautilus_trader.adapters.jquants.providers import JQuantsInstrumentProvider
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.core.datetime import time_object_to_dt
from nautilus_trader.data.messages import (
    RequestBars,
    RequestInstrument,
    RequestInstruments,
)
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import ClientId


class JQuantsDataClient(LiveMarketDataClient):
    """
    Historical (request-only) data client for J-Quants API V2.

    J-Quants は EOD 専用でストリーミングを持たないため、subscribe 系は
    非対応 (ライブ配信は kabu STATION アダプターが担う)。
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client: JQuantsHttpClient,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        instrument_provider: JQuantsInstrumentProvider,
        config: JQuantsDataClientConfig,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=ClientId(JQUANTS),
            venue=JQUANTS_VENUE,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
            config=config,
        )
        self._client = client
        self._use_adjusted = config.use_adjusted

    async def _connect(self) -> None:
        await self._instrument_provider.initialize()
        for instrument in self._instrument_provider.get_all().values():
            self._handle_data(instrument)

    async def _disconnect(self) -> None:
        await self._client.aclose()

    async def _request_instruments(self, request: RequestInstruments) -> None:
        instruments = []
        async for row in self._client.get_listed():
            try:
                instruments.append(parse_equity(row, ts_init=self._clock.timestamp_ns()))
            except Exception as e:
                self._log.warning(f"Skipping instrument row {row.get('Code')}: {e}")
        self._handle_instruments(
            request.venue,
            instruments,
            request.id,
            request.start,
            request.end,
            request.params,
        )

    async def _request_instrument(self, request: RequestInstrument) -> None:
        await self._instrument_provider.load_async(request.instrument_id)
        instrument = self._instrument_provider.find(request.instrument_id)
        if instrument is None:
            self._log.error(f"Instrument {request.instrument_id} not found in J-Quants master")
            return
        self._handle_instrument(
            instrument,
            request.id,
            request.start,
            request.end,
            request.params,
        )

    async def _request_bars(self, request: RequestBars) -> None:
        bar_type = request.bar_type
        spec = bar_type.spec
        if (
            bar_type.aggregation_source != AggregationSource.EXTERNAL
            or spec.aggregation != BarAggregation.DAY
            or spec.step != 1
            or spec.price_type != PriceType.LAST
        ):
            self._log.error(
                f"Cannot request {bar_type}: only 1-DAY-LAST-EXTERNAL bars are "
                "available from J-Quants",
            )
            return

        code = from_ticker(bar_type.instrument_id.symbol.value)
        start = time_object_to_dt(request.start).date() if request.start else None
        end = time_object_to_dt(request.end).date() if request.end else None
        rows = [
            parse_daily_bar_row(r)
            async for r in self._client.get_daily_bars(code=code, from_=start, to=end)
        ]
        factors = suffix_factors(rows) if self._use_adjusted else {}
        bars = []
        for raw in sorted(rows, key=lambda r: r.date):
            bar = make_bar(bar_type, raw, factors.get(raw.date, 1.0))
            if bar is not None:
                bars.append(bar)
        if request.limit:
            bars = bars[-request.limit :]
        self._handle_bars(
            bar_type,
            bars,
            request.id,
            request.start,
            request.end,
            request.params,
        )
