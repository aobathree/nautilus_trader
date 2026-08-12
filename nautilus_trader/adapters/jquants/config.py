import os

from nautilus_trader.adapters.jquants.constants import JQUANTS_BASE_URL
from nautilus_trader.config import LiveDataClientConfig


class JQuantsDataClientConfig(LiveDataClientConfig, frozen=True):
    """
    Configuration for `JQuantsDataClient`.

    ``api_key`` は通常 None のままにし、環境変数 ``JQUANTS_API_KEY``
    (1Password ``op run`` で注入) から解決する。
    """

    api_key: str | None = None
    base_url: str = JQUANTS_BASE_URL
    request_interval_ms: int = 300
    http_timeout_secs: float = 120.0
    max_retries: int = 6
    use_adjusted: bool = True  # request_bars で調整済みバーを返す


def resolve_api_key(config: JQuantsDataClientConfig | None = None) -> str:
    api_key = (config.api_key if config else None) or os.environ.get("JQUANTS_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "JQUANTS_API_KEY is not set. Run via: op run --env-file=.env.1password -- <command>",
        )
    return api_key
