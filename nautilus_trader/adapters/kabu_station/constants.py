from typing import Final

from nautilus_trader.model.identifiers import Venue


KABU: Final[str] = "KABU_STATION"
KABU_VENUE: Final[Venue] = Venue("XTKS")  # jQuants アダプターと同一 venue (設計書 §7)

PORT_PRODUCTION: Final[int] = 18080
PORT_PRACTICE: Final[int] = 18081

MAX_REGISTERED_SYMBOLS: Final[int] = 50  # PUSH 登録上限 (REST/PUSH 共通)

# --- kabusapi 定数 (OpenAPI v1.5) ---
SIDE_SELL: Final[str] = "1"
SIDE_BUY: Final[str] = "2"

CASH_MARGIN_CASH: Final[int] = 1  # 現物
CASH_MARGIN_OPEN: Final[int] = 2  # 信用新規
CASH_MARGIN_CLOSE: Final[int] = 3  # 信用返済

FRONT_ORDER_TYPE_MARKET: Final[int] = 10
FRONT_ORDER_TYPE_MOO_AM: Final[int] = 13  # 寄成 (前場)
FRONT_ORDER_TYPE_MOC_PM: Final[int] = 16  # 引成 (後場)
FRONT_ORDER_TYPE_LIMIT: Final[int] = 20
FRONT_ORDER_TYPE_STOP: Final[int] = 30  # 逆指値

UNDER_OVER_BELOW: Final[int] = 1  # 以下
UNDER_OVER_ABOVE: Final[int] = 2  # 以上
AFTER_HIT_MARKET: Final[int] = 1
AFTER_HIT_LIMIT: Final[int] = 2

DELIV_TYPE_UNSPECIFIED: Final[int] = 0
DELIV_TYPE_DEPOSIT: Final[int] = 2  # お預り金

FUND_TYPE_SELL: Final[str] = "  "  # 現物売 (半角スペース2つ)
FUND_TYPE_PROTECTED: Final[str] = "02"
FUND_TYPE_MARGIN: Final[str] = "11"

# /orders の状態コード
ORDER_STATE_DONE: Final[int] = 5
REC_TYPE_RECEIVED: Final[int] = 1
REC_TYPE_CARRIED: Final[int] = 2
REC_TYPE_EXPIRED: Final[int] = 3
REC_TYPE_ORDERED: Final[int] = 4
REC_TYPE_MODIFIED: Final[int] = 5
REC_TYPE_CANCELED: Final[int] = 6
REC_TYPE_REVOKED: Final[int] = 7
REC_TYPE_FILLED: Final[int] = 8
DETAIL_STATE_ERROR: Final[int] = 4
