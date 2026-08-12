import time

from nautilus_trader.adapters.jquants.http.client import JQuantsHttpClient
from nautilus_trader.adapters.jquants.parsing import parse_equity
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.model.identifiers import InstrumentId


class JQuantsInstrumentProvider(InstrumentProvider):
    """
    Instrument provider backed by ``/v2/equities/master``.

    銘柄マスタは1リクエスト(+ページネーション)で全件取得できるため、
    `load_ids_async` も内部では全件取得してからフィルタする。
    """

    def __init__(
        self,
        client: JQuantsHttpClient,
        config: InstrumentProviderConfig | None = None,
    ) -> None:
        super().__init__(config=config)
        self._client = client

    async def load_all_async(self, filters: dict | None = None) -> None:
        ts = time.time_ns()
        count = 0
        async for row in self._client.get_listed():
            try:
                equity = parse_equity(row, ts_init=ts)
            except Exception as e:
                self._log.warning(f"Skipping instrument row {row.get('Code')}: {e}")
                continue
            self.add(equity)
            count += 1
        self._log.info(f"Loaded {count} instruments from J-Quants master")

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        wanted = {i.symbol.value for i in instrument_ids}
        ts = time.time_ns()
        async for row in self._client.get_listed():
            try:
                equity = parse_equity(row, ts_init=ts)
            except Exception:
                continue
            if equity.id.symbol.value in wanted:
                self.add(equity)

    async def load_async(
        self,
        instrument_id: InstrumentId,
        filters: dict | None = None,
    ) -> None:
        await self.load_ids_async([instrument_id], filters)
