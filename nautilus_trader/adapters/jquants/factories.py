import asyncio

from nautilus_trader.adapters.jquants.config import JQuantsDataClientConfig, resolve_api_key
from nautilus_trader.adapters.jquants.data import JQuantsDataClient
from nautilus_trader.adapters.jquants.http.client import JQuantsHttpClient
from nautilus_trader.adapters.jquants.providers import JQuantsInstrumentProvider
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.live.factories import LiveDataClientFactory


class JQuantsLiveDataClientFactory(LiveDataClientFactory):
    @staticmethod
    def create(  # type: ignore[override]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: JQuantsDataClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> JQuantsDataClient:
        client = JQuantsHttpClient(
            api_key=resolve_api_key(config),
            base_url=config.base_url,
            request_interval_ms=config.request_interval_ms,
            timeout_secs=config.http_timeout_secs,
            max_retries=config.max_retries,
        )
        provider = JQuantsInstrumentProvider(
            client=client,
            config=config.instrument_provider,
        )
        return JQuantsDataClient(
            loop=loop,
            client=client,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=provider,
            config=config,
        )
