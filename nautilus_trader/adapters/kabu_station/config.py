import os

from nautilus_trader.config import LiveDataClientConfig, LiveExecClientConfig


def _base_url(environment: str) -> str:
    port = 18080 if environment == "production" else 18081
    return f"http://localhost:{port}/kabusapi"


class KabuStationDataClientConfig(LiveDataClientConfig, frozen=True):
    api_password: str | None = None  # None -> env KABU_STATION_API_PASSWORD
    environment: str = "practice"  # 既定は検証環境 (本番は明示指定)
    exchange: int = 1  # 板購読の市場 (1=東証)


class KabuStationExecClientConfig(LiveExecClientConfig, frozen=True):
    api_password: str | None = None
    order_password: str | None = None  # None -> env KABU_STATION_ORDER_PASSWORD
    environment: str = "practice"
    trading_enabled: bool = False  # 明示 True にしない限り発注拒否 (誤発注ガード)
    use_margin: bool = False
    exchange: int = 9  # SOR
    account_type: int = 4  # 特定
    margin_trade_type: int = 1  # 制度
    poll_interval_secs: float = 1.0


def resolve_api_password(config) -> str:
    pw = getattr(config, "api_password", None) or os.environ.get("KABU_STATION_API_PASSWORD", "")
    if not pw:
        raise RuntimeError(
            "KABU_STATION_API_PASSWORD is not set. "
            "Run via: op run --env-file=.env.1password -- <command>",
        )
    return pw


def resolve_order_password(config) -> str | None:
    return getattr(config, "order_password", None) or os.environ.get(
        "KABU_STATION_ORDER_PASSWORD",
    )
