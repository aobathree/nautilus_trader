"""
Pure functions for the kabu STATION adapter (unit-test target).

- 発注リクエスト組立 (設計書 §6.3 のマッピング表)
- PUSH board 全量 -> 差分ティック抽出 (Buy1/Sell1 のみ使用 —
  kabusapi の BidPrice/AskPrice は欧米慣習と逆のため触らない)
"""

import datetime as dt
from dataclasses import dataclass

from nautilus_trader.adapters.kabu_station.constants import (
    AFTER_HIT_LIMIT,
    AFTER_HIT_MARKET,
    CASH_MARGIN_CASH,
    CASH_MARGIN_CLOSE,
    CASH_MARGIN_OPEN,
    DELIV_TYPE_DEPOSIT,
    DELIV_TYPE_UNSPECIFIED,
    FRONT_ORDER_TYPE_LIMIT,
    FRONT_ORDER_TYPE_MARKET,
    FRONT_ORDER_TYPE_MOC_PM,
    FRONT_ORDER_TYPE_MOO_AM,
    FRONT_ORDER_TYPE_STOP,
    FUND_TYPE_MARGIN,
    FUND_TYPE_PROTECTED,
    FUND_TYPE_SELL,
    SIDE_BUY,
    SIDE_SELL,
    UNDER_OVER_ABOVE,
    UNDER_OVER_BELOW,
)
from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.model.enums import AggressorSide, OrderSide, OrderType, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId, TradeId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.orders import Order


def expire_day(tif: TimeInForce, expire_time: dt.datetime | None) -> int:
    """DAY -> 0 (当日)、GTD -> yyyyMMdd。GTC は非対応 (日次失効のため明示拒否)。"""
    if tif == TimeInForce.DAY:
        return 0
    if tif == TimeInForce.GTD and expire_time is not None:
        d = expire_time.date()
        return d.year * 10000 + d.month * 100 + d.day
    raise ValueError(f"Unsupported TimeInForce for kabusapi: {tif} (use DAY or GTD)")


def derive_cash_margin(
    side: OrderSide,
    quantity: int,
    open_long: int,
    open_short: int,
    use_margin: bool,
) -> int:
    """
    現物 / 信用新規 / 信用返済の自動判定。

    反対建玉があれば返済、無ければ新規。反対建玉数量を超える注文 (ドテン) は
    拒否 — kabusapi は1注文で返済+新規ができないため注文分割が必要。
    """
    if not use_margin:
        return CASH_MARGIN_CASH
    opposite = open_short if side == OrderSide.BUY else open_long
    if opposite == 0:
        return CASH_MARGIN_OPEN
    if quantity > opposite:
        raise ValueError(
            f"Order qty {quantity} exceeds opposite position {opposite} (doten): "
            "split into close + open orders",
        )
    return CASH_MARGIN_CLOSE


def build_reverse_limit(
    side: OrderSide,
    trigger_price: float,
    limit_price: float | None,
) -> dict:
    """買い逆指値 -> 以上 (UnderOver=2)、売り逆指値 -> 以下 (UnderOver=1)。"""
    return {
        "TriggerSec": 1,  # 発注銘柄
        "TriggerPrice": float(trigger_price),
        "UnderOver": UNDER_OVER_ABOVE if side == OrderSide.BUY else UNDER_OVER_BELOW,
        "AfterHitOrderType": AFTER_HIT_MARKET if limit_price is None else AFTER_HIT_LIMIT,
        "AfterHitPrice": float(limit_price) if limit_price is not None else 0.0,
    }


def build_sendorder(
    order: Order,
    open_long: int = 0,
    open_short: int = 0,
    use_margin: bool = False,
    exchange: int = 9,  # SOR
    security_type: int = 1,
    account_type: int = 4,  # 特定
    margin_trade_type: int = 1,  # 制度
    fund_type_cash_buy: str = FUND_TYPE_PROTECTED,
    lot_size: int = 100,
) -> dict:
    """Nautilus Order -> POST /sendorder payload (Password はクライアント層で付与)。"""
    qty = int(order.quantity)
    if qty % lot_size != 0:
        raise ValueError(f"Quantity {qty} is not a multiple of lot size {lot_size}")

    front_type: int
    price = 0.0
    reverse_limit: dict | None = None
    if order.order_type == OrderType.MARKET:
        if order.time_in_force == TimeInForce.AT_THE_OPEN:
            front_type = FRONT_ORDER_TYPE_MOO_AM
        elif order.time_in_force == TimeInForce.AT_THE_CLOSE:
            front_type = FRONT_ORDER_TYPE_MOC_PM
        else:
            front_type = FRONT_ORDER_TYPE_MARKET
    elif order.order_type == OrderType.LIMIT:
        front_type = FRONT_ORDER_TYPE_LIMIT
        price = float(order.price)
    elif order.order_type == OrderType.STOP_MARKET:
        front_type = FRONT_ORDER_TYPE_STOP
        reverse_limit = build_reverse_limit(order.side, float(order.trigger_price), None)
    elif order.order_type == OrderType.STOP_LIMIT:
        front_type = FRONT_ORDER_TYPE_STOP
        reverse_limit = build_reverse_limit(
            order.side,
            float(order.trigger_price),
            float(order.price),
        )
    else:
        raise ValueError(f"Unsupported order type for kabusapi: {order.order_type}")

    if order.time_in_force in (TimeInForce.AT_THE_OPEN, TimeInForce.AT_THE_CLOSE):
        day = 0
    else:
        day = expire_day(order.time_in_force, getattr(order, "expire_time", None))

    cash_margin = derive_cash_margin(order.side, qty, open_long, open_short, use_margin)
    is_buy = order.side == OrderSide.BUY
    payload: dict = {
        "Symbol": order.instrument_id.symbol.value,
        "Exchange": exchange,
        "SecurityType": security_type,
        "Side": SIDE_BUY if is_buy else SIDE_SELL,
        "CashMargin": cash_margin,
        "AccountType": account_type,
        "Qty": qty,
        "FrontOrderType": front_type,
        "Price": price,
        "ExpireDay": day,
    }
    if cash_margin == CASH_MARGIN_CASH:
        payload["DelivType"] = DELIV_TYPE_DEPOSIT if is_buy else DELIV_TYPE_UNSPECIFIED
        payload["FundType"] = fund_type_cash_buy if is_buy else FUND_TYPE_SELL
    else:
        payload["MarginTradeType"] = margin_trade_type
        payload["DelivType"] = (
            DELIV_TYPE_DEPOSIT if cash_margin == CASH_MARGIN_CLOSE else DELIV_TYPE_UNSPECIFIED
        )
        payload["FundType"] = FUND_TYPE_MARGIN
        if cash_margin == CASH_MARGIN_CLOSE:
            payload["ClosePositionOrder"] = 0  # 日付古い順・損益高い順
    if reverse_limit is not None:
        payload["ReverseLimitOrder"] = reverse_limit
    return payload


@dataclass
class BoardState:
    """銘柄ごとの前回 board 状態 (PUSH は差分でなく全量が届く)。"""

    current_price_time: str | None = None
    trading_volume: float | None = None
    buy1_price: float | None = None
    buy1_qty: float | None = None
    sell1_price: float | None = None
    sell1_qty: float | None = None


def extract_ticks(
    board: dict,
    state: BoardState,
    instrument_id: InstrumentId,
    ts_init: int,
    price_precision: int = 1,
) -> list:
    """
    board 全量と前回状態を比較して差分ティックを生成する (LEAN 版 ExtractTicks 移植)。

    - TradeTick: CurrentPriceTime か TradingVolume の変化で生成。数量は出来高差分
      (負ならセッション開始のリセットと判定し、当日出来高を数量とする)
    - QuoteTick: Buy1/Sell1 の価格・数量の変化で生成 (bid=Buy1, ask=Sell1)
    """
    ticks: list = []
    buy1 = board.get("Buy1") or {}
    sell1 = board.get("Sell1") or {}
    b_px, b_qty = buy1.get("Price"), buy1.get("Qty")
    s_px, s_qty = sell1.get("Price"), sell1.get("Qty")
    px_time = board.get("CurrentPriceTime")
    px = board.get("CurrentPrice")
    volume = board.get("TradingVolume")

    quote_changed = (b_px, b_qty, s_px, s_qty) != (
        state.buy1_price,
        state.buy1_qty,
        state.sell1_price,
        state.sell1_qty,
    )
    if quote_changed and None not in (b_px, b_qty, s_px, s_qty):
        ticks.append(
            QuoteTick(
                instrument_id,
                Price(float(b_px), price_precision),
                Price(float(s_px), price_precision),
                Quantity(float(b_qty), 0),
                Quantity(float(s_qty), 0),
                ts_init,
                ts_init,
            ),
        )

    trade_changed = px_time is not None and (
        px_time != state.current_price_time
        or (volume is not None and volume != state.trading_volume)
    )
    is_first = state.current_price_time is None and state.trading_volume is None
    if trade_changed and not is_first and px is not None:
        delta = float(volume or 0) - float(state.trading_volume or 0)
        size = float(volume or 0) if delta < 0 else delta  # 負 = セッションリセット
        if size > 0:
            ticks.append(
                TradeTick(
                    instrument_id,
                    Price(float(px), price_precision),
                    Quantity(size, 0),
                    AggressorSide.NO_AGGRESSOR,  # kabusapi は約定方向を配信しない
                    TradeId(f"{px_time}-{int(float(volume or 0))}"),
                    ts_init,
                    ts_init,
                ),
            )

    state.current_price_time = px_time
    state.trading_volume = volume
    state.buy1_price, state.buy1_qty = b_px, b_qty
    state.sell1_price, state.sell1_qty = s_px, s_qty
    return ticks


def updtime_cursor(now: dt.datetime) -> str:
    """/orders ポーリングカーソル: リクエスト時刻 - 30秒 (オーバーラップ)。"""
    return (now - dt.timedelta(seconds=30)).strftime("%Y%m%d%H%M%S")
