"""
J-Quants -> ParquetDataCatalog ETL CLI.

Commands
--------
- backfill : code 軸で一括取得 (初期構築 / 調整係数変更後の再生成)
- update   : date 軸で日次増分 (新しい AdjFactor を検出したら backfill を促す)
- calendar : 営業日カレンダーを CSV 出力
- verify   : 未調整 x 累積係数 ≒ AdjC を照合 (許容誤差 max(0.1, AdjC*0.2%))

Catalog layout: ``<root>/adjusted`` (調整済み・バックテスト既定) and
``<root>/raw`` (未調整・正のデータ)。

Usage (secrets via 1Password):
    op run --env-file=.env.1password -- python -m nautilus_trader.adapters.jquants.scripts.jquants_etl backfill --codes 8316,7203 --catalog D:/nautilus_trader/catalog
"""

import argparse
import asyncio
import datetime as dt
import shutil
import sys
from pathlib import Path

from nautilus_trader.adapters.jquants.config import resolve_api_key
from nautilus_trader.adapters.jquants.http.client import JQuantsHttpClient
from nautilus_trader.adapters.jquants.parsing import (
    RawDailyBar,
    is_trading_day,
    make_bar,
    parse_calendar_row,
    parse_daily_bar_row,
    parse_equity,
    suffix_factors,
    to_ticker,
)
from nautilus_trader.model.data import BarType
from nautilus_trader.persistence.catalog import ParquetDataCatalog


MIN_FREE_GB_DEFAULT = 5


def _bar_type(ticker: str) -> BarType:
    return BarType.from_str(f"{ticker}.XTKS-1-DAY-LAST-EXTERNAL")


def _check_disk(path: Path, min_free_gb: int) -> None:
    free_gb = shutil.disk_usage(path.anchor or ".").free / 1024**3
    if free_gb < min_free_gb:
        raise RuntimeError(f"Disk free {free_gb:.1f}GB < {min_free_gb}GB, aborting")


def _write_code(
    catalog_root: Path,
    ticker: str,
    rows: list[RawDailyBar],
) -> tuple[int, int]:
    bar_type = _bar_type(ticker)
    factors = suffix_factors(rows)
    raw_bars, adj_bars = [], []
    for raw in sorted(rows, key=lambda r: r.date):
        b_raw = make_bar(bar_type, raw, 1.0)
        if b_raw is None:
            continue
        raw_bars.append(b_raw)
        adj_bars.append(make_bar(bar_type, raw, factors[raw.date]))
    if raw_bars:
        ParquetDataCatalog(str(catalog_root / "raw")).write_data(raw_bars)
        ParquetDataCatalog(str(catalog_root / "adjusted")).write_data(adj_bars)
    return len(raw_bars), len(adj_bars)


async def _load_instruments(client: JQuantsHttpClient, tickers: set[str] | None) -> list:
    instruments = []
    async for row in client.get_listed():
        try:
            eq = parse_equity(row)
        except Exception:
            continue
        if tickers is None or eq.id.symbol.value in tickers:
            instruments.append(eq)
    return instruments


async def cmd_backfill(client: JQuantsHttpClient, args) -> int:
    root = Path(args.catalog)
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",")]
    else:  # --all
        codes = sorted({str(r["Code"]) async for r in client.get_listed()})
    print(f"backfill: {len(codes)} codes -> {root}")
    instruments = await _load_instruments(client, {to_ticker(c) for c in codes})
    ParquetDataCatalog(str(root / "raw")).write_data(instruments)
    ParquetDataCatalog(str(root / "adjusted")).write_data(instruments)
    from_ = dt.date.fromisoformat(args.from_) if args.from_ else None
    to = dt.date.fromisoformat(args.to) if args.to else None
    total = 0
    for i, code in enumerate(codes):
        if i % 500 == 0:
            _check_disk(root, args.min_free_gb)
        rows = [
            parse_daily_bar_row(r)
            async for r in client.get_daily_bars(code=code, from_=from_, to=to)
        ]
        if not rows:
            print(f"  {code}: no data")
            continue
        n, _ = _write_code(root, to_ticker(code), rows)
        total += n
        print(f"  {code}: {n} bars")
    print(f"backfill done: {total} bars total")
    return 0


async def cmd_update(client: JQuantsHttpClient, args) -> int:
    root = Path(args.catalog)
    date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    rows = await _rows_with_code(client, date)
    if not rows:
        print(f"update {date}: no data (holiday or not yet published)")
        return 0
    needs_backfill = []
    raw_bars, adj_bars = [], []
    for raw, code in rows:
        ticker = to_ticker(code)
        bar_type = _bar_type(ticker)
        if raw.adj_factor != 1.0:
            needs_backfill.append(code)
        b = make_bar(bar_type, raw, 1.0)
        if b is not None:
            raw_bars.append(b)
            adj_bars.append(b)  # 当日時点の累積係数は 1
    if raw_bars:
        ParquetDataCatalog(str(root / "raw")).write_data(raw_bars)
        ParquetDataCatalog(str(root / "adjusted")).write_data(adj_bars)
    print(f"update {date}: {len(raw_bars)} bars written")
    if needs_backfill:
        print(
            f"WARNING: AdjFactor != 1 detected for {needs_backfill} — run "
            f"`backfill --codes {','.join(needs_backfill)}` to regenerate adjusted series",
        )
    return 0


async def _rows_with_code(
    client: JQuantsHttpClient,
    date: dt.date,
) -> list[tuple[RawDailyBar, str]]:
    return [
        (parse_daily_bar_row(r), str(r["Code"]))
        async for r in client.get_daily_bars(date=date)
    ]


async def cmd_calendar(client: JQuantsHttpClient, args) -> int:
    from_ = dt.date.fromisoformat(args.from_)
    to = dt.date.fromisoformat(args.to)
    out = Path(args.out)
    lines = ["date,hol_div,is_trading_day"]
    async for row in client.get_calendar(from_, to):
        d, hol = parse_calendar_row(row)
        lines.append(f"{d.isoformat()},{hol},{int(is_trading_day(hol))}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"calendar: {len(lines) - 1} days -> {out}")
    return 0


async def cmd_verify(client: JQuantsHttpClient, args) -> int:
    codes = [c.strip() for c in args.codes.split(",")]
    failures = 0
    for code in codes:
        rows = [parse_daily_bar_row(r) async for r in client.get_daily_bars(code=code)]
        factors = suffix_factors(rows)
        bad = 0
        for raw in rows:
            if raw.close is None or raw.adj_close is None:
                continue
            calc = raw.close * factors[raw.date]
            tol = max(0.1, float(raw.adj_close) * 0.002)
            if abs(calc - float(raw.adj_close)) > tol:
                bad += 1
                if bad <= 3:
                    print(f"  {code} {raw.date}: calc={calc:.2f} AdjC={raw.adj_close}")
        status = "OK" if bad == 0 else f"FAIL ({bad} rows)"
        print(f"verify {code}: {len(rows)} rows, {status}")
        failures += bad
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jquants_etl")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backfill")
    b.add_argument("--codes", help="comma-separated J-Quants codes (e.g. 8316,72030)")
    b.add_argument("--all", action="store_true")
    b.add_argument("--from", dest="from_", help="YYYY-MM-DD (Standard プランでは省略推奨)")
    b.add_argument("--to", help="YYYY-MM-DD")
    b.add_argument("--catalog", required=True)
    b.add_argument("--min-free-gb", type=int, default=MIN_FREE_GB_DEFAULT)

    u = sub.add_parser("update")
    u.add_argument("--date", help="YYYY-MM-DD (default: today)")
    u.add_argument("--catalog", required=True)

    c = sub.add_parser("calendar")
    c.add_argument("--from", dest="from_", required=True)
    c.add_argument("--to", required=True)
    c.add_argument("--out", default="trading_calendar.csv")

    v = sub.add_parser("verify")
    v.add_argument("--codes", required=True)

    args = p.parse_args(argv)
    if args.cmd == "backfill" and not (args.codes or args.all):
        p.error("backfill requires --codes or --all")

    client = JQuantsHttpClient(api_key=resolve_api_key())

    async def run() -> int:
        try:
            return await {
                "backfill": cmd_backfill,
                "update": cmd_update,
                "calendar": cmd_calendar,
                "verify": cmd_verify,
            }[args.cmd](client, args)
        finally:
            await client.aclose()

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
