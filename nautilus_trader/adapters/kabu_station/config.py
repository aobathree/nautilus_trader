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
    environment: str = "practice"
    trading_enabled: bool = False  # 明示 True にしない限り発注拒否 (誤発注ガード)
    use_margin: bool = False
    exchange: int = 9  # SOR
    account_type: int = 4  # 特定
    margin_trade_type: int = 1  # 制度
    poll_interval_secs: float = 1.0


def resolve_api_password(config) -> str:
    """
    API パスワードは kabu STATION の「APIシステム設定」で本番用・検証用が
    別々に発行される。config.environment に対応する環境変数を優先し、
    共通の KABU_STATION_API_PASSWORD にフォールバックする。
    """
    if getattr(config, "api_password", None):
        return config.api_password
    env = getattr(config, "environment", "practice")
    suffix = "PRODUCTION" if env == "production" else "PRACTICE"
    pw = os.environ.get(f"KABU_STATION_API_PASSWORD_{suffix}") or os.environ.get(
        "KABU_STATION_API_PASSWORD",
        "",
    )
    if not pw:
        raise RuntimeError(
            f"KABU_STATION_API_PASSWORD_{suffix} (or KABU_STATION_API_PASSWORD) is not set. "
            "Run via: op run --env-file=.env.1password -- <command>",
        )
    return pw
