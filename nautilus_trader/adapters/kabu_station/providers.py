from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.model.identifiers import InstrumentId


class KabuStationInstrumentProvider(InstrumentProvider):
    """
    最小実装。インストルメントの正は jQuants アダプター
    (`JQuantsInstrumentProvider`) が担う (設計書 §7)。

    kabu STATION 単体で使う場合は TradingNode 側で instruments を
    キャッシュにロードしておくこと。
    """

    def __init__(self, config: InstrumentProviderConfig | None = None) -> None:
        super().__init__(config=config)

    async def load_all_async(self, filters: dict | None = None) -> None:
        self._log.info("KabuStationInstrumentProvider: instruments are provided by jQuants")

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        pass

    async def load_async(
        self,
        instrument_id: InstrumentId,
        filters: dict | None = None,
    ) -> None:
        pass
