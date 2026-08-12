import datetime as dt
from types import SimpleNamespace

import pytest

from nautilus_trader.adapters.kabu_station.parsing import (
    build_reverse_limit,
    build_sendorder,
    derive_cash_margin,
    expire_day,
)
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId


def order(
    order_type=OrderType.LIMIT,
    side=OrderSide.BUY,
    qty=100,
    price=6000.0,
    trigger=None,
    tif=TimeInForce.DAY,
    expire=None,
):
    return SimpleNamespace(
        instrument_id=InstrumentId.from_str("7203.XTKS"),
        order_type=order_type,
        side=side,
        quantity=qty,
        price=price,
        trigger_price=trigger,
        time_in_force=tif,
        expire_time=expire,
    )


def test_cash_buy_limit():
    p = build_sendorder(order())
    assert p["Symbol"] == "7203"
    assert p["Side"] == "2"
    assert p["CashMargin"] == 1
    assert p["FrontOrderType"] == 20
    assert p["Price"] == 6000.0
    assert p["DelivType"] == 2
    assert p["FundType"] == "02"
    assert p["ExpireDay"] == 0
    assert p["Exchange"] == 9  # SOR


def test_cash_sell_fund_type_spaces():
    p = build_sendorder(order(side=OrderSide.SELL, order_type=OrderType.MARKET, price=None))
    assert p["FrontOrderType"] == 10
    assert p["DelivType"] == 0
    assert p["FundType"] == "  "


def test_market_on_open_and_close():
    p = build_sendorder(order(order_type=OrderType.MARKET, price=None, tif=TimeInForce.AT_THE_OPEN))
    assert p["FrontOrderType"] == 13
    p = build_sendorder(order(order_type=OrderType.MARKET, price=None, tif=TimeInForce.AT_THE_CLOSE))
    assert p["FrontOrderType"] == 16


def test_stop_market_buy_triggers_above():
    p = build_sendorder(order(order_type=OrderType.STOP_MARKET, price=None, trigger=6100.0))
    rl = p["ReverseLimitOrder"]
    assert p["FrontOrderType"] == 30
    assert rl["UnderOver"] == 2  # 買い逆指値 = 以上
    assert rl["AfterHitOrderType"] == 1
    assert rl["TriggerSec"] == 1


def test_stop_limit_sell_triggers_below():
    p = build_sendorder(
        order(order_type=OrderType.STOP_LIMIT, side=OrderSide.SELL, price=5900.0, trigger=5950.0),
    )
    rl = p["ReverseLimitOrder"]
    assert rl["UnderOver"] == 1  # 売り逆指値 = 以下
    assert rl["AfterHitOrderType"] == 2
    assert rl["AfterHitPrice"] == 5900.0


def test_margin_open_and_close():
    p = build_sendorder(order(), use_margin=True)
    assert p["CashMargin"] == 2
    assert p["FundType"] == "11"
    assert p["MarginTradeType"] == 1
    p = build_sendorder(order(), use_margin=True, open_short=100)
    assert p["CashMargin"] == 3
    assert p["DelivType"] == 2
    assert p["ClosePositionOrder"] == 0


@pytest.mark.parametrize(
    ("side", "qty", "long_", "short", "expected"),
    [
        (OrderSide.BUY, 100, 0, 0, 2),  # 新規買建
        (OrderSide.SELL, 100, 0, 0, 2),  # 新規売建
        (OrderSide.BUY, 100, 0, 100, 3),  # 買が売建を返済
        (OrderSide.SELL, 100, 100, 0, 3),  # 売が買建を返済
        (OrderSide.BUY, 100, 100, 0, 2),  # 同方向は新規
        (OrderSide.SELL, 100, 300, 0, 3),  # 部分返済
    ],
)
def test_derive_cash_margin_cases(side, qty, long_, short, expected):
    assert derive_cash_margin(side, qty, long_, short, use_margin=True) == expected


def test_doten_rejected():
    with pytest.raises(ValueError, match="doten"):
        derive_cash_margin(OrderSide.SELL, 200, 100, 0, use_margin=True)


def test_expire_day():
    assert expire_day(TimeInForce.DAY, None) == 0
    assert expire_day(TimeInForce.GTD, dt.datetime(2026, 9, 30)) == 20260930
    with pytest.raises(ValueError):
        expire_day(TimeInForce.GTC, None)  # GTC は日次失効するため拒否


def test_odd_lot_rejected():
    with pytest.raises(ValueError, match="lot size"):
        build_sendorder(order(qty=150))


def test_reverse_limit_direct():
    rl = build_reverse_limit(OrderSide.BUY, 100.0, None)
    assert rl == {
        "TriggerSec": 1,
        "TriggerPrice": 100.0,
        "UnderOver": 2,
        "AfterHitOrderType": 1,
        "AfterHitPrice": 0.0,
    }
