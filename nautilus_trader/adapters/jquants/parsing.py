"""
Pure functions: J-Quants V2 JSON rows -> Nautilus objects.

V2 uses short column names (``O/H/L/C/Vo/AdjFactor/AdjC``); V1 long names are
accepted as fallback. Kept side-effect free for unit testing.
"""

import datetime as dt
from dataclasses import dataclass

from nautilus_trader.adapters.jquants.constants import JQUANTS_VENUE
from nautilus_trader.model.currencies import JPY
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Price, Quantity


JST = dt.timezone(dt.timedelta(hours=9))
# 大引けが 15:00 -> 15:30 に変更された日
CLOSE_CHANGE_DATE = dt.date(2024, 11, 5)


def to_ticker(code: str) -> str:
    # J-Quants 5桁コード -> 4桁ティッカー (72030 -> 7203)。末尾が 0 以外 (25935 等) はそのまま
    code = str(code).strip()
    if len(code) == 5 and code.endswith("0"):
        return code[:-1]
    return code


def from_ticker(ticker: str) -> str:
    return ticker if len(ticker) == 5 else ticker + "0"


def parse_date(value: str) -> dt.date:
    s = str(value).replace("-", "")
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def close_ts_ns(d: dt.date) -> int:
    close = dt.time(15, 30) if d >= CLOSE_CHANGE_DATE else dt.time(15, 0)
    return int(dt.datetime.combine(d, close, tzinfo=JST).timestamp() * 1_000_000_000)


@dataclass(frozen=True)
class RawDailyBar:
    date: dt.date
    open: float | None  # 売買なしの日は OHLCV が None (AdjFactor は有効)
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    adj_factor: float
    adj_close: float | None


def _first(row: dict, *names: str):
    for n in names:
        if row.get(n) is not None:
            return row[n]
    return None


def parse_daily_bar_row(row: dict) -> RawDailyBar:
    return RawDailyBar(
        date=parse_date(row["Date"]),
        open=_first(row, "O", "Open"),
        high=_first(row, "H", "High"),
        low=_first(row, "L", "Low"),
        close=_first(row, "C", "Close"),
        volume=_first(row, "Vo", "Volume"),
        adj_factor=float(_first(row, "AdjFactor", "AdjustmentFactor") or 1.0),
        adj_close=_first(row, "AdjC", "AdjustmentClose"),
    )


def suffix_factors(rows: list[RawDailyBar]) -> dict[dt.date, float]:
    """
    日付 t ごとの累積調整係数 = Π_{d > t} adj_factor(d)。

    AdjFactor は権利落ち日 d に記録され、d より前の価格に適用される。
    """
    result: dict[dt.date, float] = {}
    cum = 1.0
    for raw in sorted(rows, key=lambda r: r.date, reverse=True):
        result[raw.date] = cum
        cum *= raw.adj_factor
    return result


def make_bar(
    bar_type: BarType,
    raw: RawDailyBar,
    factor: float = 1.0,
    price_precision: int = 1,
) -> Bar | None:
    if raw.close is None:  # 売買なしの日
        return None
    ts = close_ts_ns(raw.date)
    return Bar(
        bar_type,
        Price(float(raw.open) * factor, price_precision),
        Price(float(raw.high) * factor, price_precision),
        Price(float(raw.low) * factor, price_precision),
        Price(float(raw.close) * factor, price_precision),
        Quantity(round(float(raw.volume or 0) / factor if factor else 0), 0),
        ts,
        ts,
    )


def parse_equity(row: dict, ts_init: int = 0) -> Equity:
    code = str(row["Code"]).strip()
    ticker = to_ticker(code)
    return Equity(
        instrument_id=InstrumentId(Symbol(ticker), JQUANTS_VENUE),
        raw_symbol=Symbol(code),
        currency=JPY,
        price_precision=1,
        price_increment=Price.from_str("0.1"),
        lot_size=Quantity.from_int(100),
        ts_event=ts_init,
        ts_init=ts_init,
    )


def parse_calendar_row(row: dict) -> tuple[dt.date, int]:
    # HolDiv: 0=非営業日 1=営業日 2=半日立会 3=非営業日(祝日取引あり)
    return parse_date(row["Date"]), int(_first(row, "HolDiv", "HolidayDivision") or 0)


def is_trading_day(hol_div: int) -> bool:
    return hol_div in (1, 2)
