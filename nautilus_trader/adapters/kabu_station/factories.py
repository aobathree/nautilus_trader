import asyncio

from nautilus_trader.adapters.kabu_station.config import (
    KabuStationDataClientConfig,
    KabuStationExecClientConfig,
    _base_url,
    resolve_api_password,
)
from nautilus_trader.adapters.kabu_station.data import KabuStationDataClient
from nautilus_trader.adapters.kabu_station.execution import KabuStationExecutionClient
from nautilus_trader.adapters.kabu_station.http.client import KabuStationHttpClient
from nautilus_trader.adapters.kabu_station.providers import KabuStationInstrumentProvider
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.live.factories import LiveDataClientFactory, LiveExecClientFactory


def _ws_url(environment: str) -> str:
    port = 18080 if environment == "production" else 18081
    return f"ws://localhost:{port}/kabusapi/websocket"


class KabuStationLiveDataClientFactory(LiveDataClientFactory):
    @staticmethod
    def create(  # type: ignore[override]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: KabuStationDataClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> KabuStationDataClient:
        client = KabuStationHttpClient(
            api_password=resolve_api_password(config),
            base_url=_base_url(config.environment),
        )
        return KabuStationDataClient(
            loop=loop,
            client=client,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=KabuStationInstrumentProvider(config.instrument_provider),
            config=config,
            ws_url=_ws_url(config.environment),
        )


class KabuStationLiveExecClientFactory(LiveExecClientFactory):
    @staticmethod
    def create(  # type: ignore[override]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: KabuStationExecClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> KabuStationExecutionClient:
        client = KabuStationHttpClient(
            api_password=resolve_api_password(config),
            base_url=_base_url(config.environment),
        )
        return KabuStationExecutionClient(
            loop=loop,
            client=client,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=KabuStationInstrumentProvider(config.instrument_provider),
            config=config,
        )
