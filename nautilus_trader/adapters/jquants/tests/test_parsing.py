import datetime as dt

import pytest

from nautilus_trader.adapters.jquants.parsing import (
    close_ts_ns,
    from_ticker,
    is_trading_day,
    make_bar,
    parse_calendar_row,
    parse_daily_bar_row,
    parse_equity,
    suffix_factors,
    to_ticker,
)
from nautilus_trader.model.data import BarType


BAR_TYPE = BarType.from_str("8316.XTKS-1-DAY-LAST-EXTERNAL")


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("72030", "7203"),  # 普通株 5桁 -> 4桁
        ("83160", "8316"),
        ("130A0", "130A"),  # 英数字コード
        ("25935", "25935"),  # 末尾 0 以外はそのまま
        ("7203", "7203"),  # 既に 4桁
    ],
)
def test_to_ticker(code, expected):
    assert to_ticker(code) == expected


@pytest.mark.parametrize("code", ["72030", "130A0", "25935"])
def test_from_ticker_roundtrip(code):
    assert from_ticker(to_ticker(code)) == code


def test_parse_daily_bar_row_v2_columns():
    row = {
        "Date": "2026-08-12",
        "Code": "83160",
        "O": 6770.0,
        "H": 6871.0,
        "L": 6726.0,
        "C": 6857.0,
        "Vo": 12391400.0,
        "AdjFactor": 1.0,
        "AdjC": 6857.0,
    }
    raw = parse_daily_bar_row(row)
    assert raw.date == dt.date(2026, 8, 12)
    assert raw.close == 6857.0
    assert raw.adj_factor == 1.0


def test_parse_daily_bar_row_v1_fallback_and_no_trade():
    row = {"Date": "20240927", "AdjustmentFactor": 0.3333333333, "AdjustmentClose": None}
    raw = parse_daily_bar_row(row)
    assert raw.close is None  # 売買なし日でも AdjFactor は有効
    assert raw.adj_factor == pytest.approx(0.3333333333)


def test_suffix_factors_applies_to_prior_dates_only():
    # 8316 相当: 2024-09-27 に 1:3 分割 (factor 0.3333...)
    rows = [
        parse_daily_bar_row({"Date": "20240925", "C": 9000.0, "AdjFactor": 1.0}),
        parse_daily_bar_row({"Date": "20240926", "C": 9174.0, "AdjFactor": 1.0}),
        parse_daily_bar_row({"Date": "20240927", "C": 3100.0, "AdjFactor": 1 / 3}),
        parse_daily_bar_row({"Date": "20240930", "C": 3150.0, "AdjFactor": 1.0}),
    ]
    f = suffix_factors(rows)
    assert f[dt.date(2024, 9, 30)] == 1.0
    assert f[dt.date(2024, 9, 27)] == 1.0  # 権利落ち日自体は調整されない
    assert f[dt.date(2024, 9, 26)] == pytest.approx(1 / 3)
    assert f[dt.date(2024, 9, 25)] == pytest.approx(1 / 3)


def test_make_bar_adjusted_price_and_volume():
    raw = parse_daily_bar_row(
        {"Date": "20240926", "O": 9000.0, "H": 9200.0, "L": 8900.0, "C": 9174.0, "Vo": 300.0},
    )
    bar = make_bar(BAR_TYPE, raw, factor=1 / 3)
    assert float(bar.close) == pytest.approx(3058.0, abs=0.1)
    assert int(bar.volume) == 900  # 出来高は係数で除算


def test_make_bar_none_for_no_trade_day():
    raw = parse_daily_bar_row({"Date": "20240927", "AdjFactor": 0.5})
    assert make_bar(BAR_TYPE, raw) is None


def test_close_ts_change_2024_11_05():
    before = close_ts_ns(dt.date(2024, 11, 1))  # 15:00 JST
    after = close_ts_ns(dt.date(2024, 11, 5))  # 15:30 JST
    assert dt.datetime.fromtimestamp(before / 1e9, dt.timezone.utc).hour == 6
    assert dt.datetime.fromtimestamp(before / 1e9, dt.timezone.utc).minute == 0
    assert dt.datetime.fromtimestamp(after / 1e9, dt.timezone.utc).minute == 30


def test_parse_equity():
    eq = parse_equity({"Code": "83160", "CoName": "三井住友FG", "MktNm": "プライム"})
    assert eq.id.value == "8316.XTKS"
    assert eq.raw_symbol.value == "83160"
    assert str(eq.quote_currency) == "JPY"
    assert int(eq.lot_size) == 100


def test_parse_calendar_row():
    d, hol = parse_calendar_row({"Date": "20260101", "HolDiv": "0"})
    assert d == dt.date(2026, 1, 1)
    assert not is_trading_day(hol)
    assert is_trading_day(1)
    assert is_trading_day(2)  # 半日立会も営業日
