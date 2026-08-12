"""
発注スモークテスト: 遠い指値 1 単元 -> 照会 -> 取消 -> 取消確認。

**実注文が発生する。ユーザー立ち会いのもと手動起動のみ。**
既定は検証環境 (18081)。本番は --production + 対話確認 (YES 入力) が必要。

実行:
    op run --env-file=D:/nautilus_trader/.env.1password -- python -m nautilus_trader.adapters.kabu_station.scripts.order_smoke_test [--production] [--symbol 7203] [--qty 100] [--discount 0.20]
"""

import argparse
import asyncio
from types import SimpleNamespace

from nautilus_trader.adapters.kabu_station.config import resolve_api_password
from nautilus_trader.adapters.kabu_station.http.client import KabuStationHttpClient
from nautilus_trader.adapters.kabu_station.parsing import build_sendorder
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId


def far_limit_price(current: float, discount: float) -> float:
    """現値から discount 離した買い指値。呼値制約を満たすよう 10円 (高額帯は 50円) に丸める。"""
    raw = current * (1.0 - discount)
    step = 50 if raw > 30_000 else 10
    return float(int(raw // step) * step)


async def wait_order(client: KabuStationHttpClient, order_id: str, attempts: int = 10) -> dict:
    for _ in range(attempts):
        for row in await client.get_orders():
            if str(row.get("ID")) == order_id:
                return row
        await asyncio.sleep(1.0)
    raise RuntimeError(f"order {order_id} not found via /orders after {attempts}s")


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--production", action="store_true")
    p.add_argument("--symbol", default="7203")
    p.add_argument("--qty", type=int, default=100)
    p.add_argument("--discount", type=float, default=0.20)
    args = p.parse_args()
    env = "production" if args.production else "practice"
    port = 18080 if args.production else 18081

    client = KabuStationHttpClient(
        api_password=resolve_api_password(SimpleNamespace(api_password=None, environment=env)),
        base_url=f"http://localhost:{port}/kabusapi",
    )
    try:
        print(f"[1/6] token ({env}) ...")
        await client.get_token()

        print(f"[2/6] /board/{args.symbol}@1 ...")
        board = await client.get_board(args.symbol)
        current = board.get("CurrentPrice")
        if not current:
            print("ABORT: CurrentPrice unavailable (market closed or invalid symbol)")
            return 1
        limit = far_limit_price(float(current), args.discount)
        cost = limit * args.qty
        print(f"       current={current}  limit={limit}  qty={args.qty}  cost={cost:,.0f} JPY")

        print("[3/6] /wallet/cash (buying power check) ...")
        wallet = await client.get_wallet_cash()
        power = float(wallet.get("StockAccountWallet") or 0)
        print(f"       StockAccountWallet={power:,.0f}")
        if args.production and power < cost:
            print("ABORT: insufficient buying power for the limit order")
            return 1

        if args.production:
            print(f"*** 本番環境に実注文を発注します: {args.symbol} 買 {args.qty}株 指値 {limit} ***")
            if input("    続行するには YES と入力: ").strip() != "YES":
                print("aborted by user")
                return 1

        order = SimpleNamespace(
            instrument_id=InstrumentId.from_str(f"{args.symbol}.XTKS"),
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            quantity=args.qty,
            price=limit,
            trigger_price=None,
            time_in_force=TimeInForce.DAY,
            expire_time=None,
        )
        payload = build_sendorder(order)
        print(f"[4/6] POST /sendorder {payload}")
        order_id = await client.send_order(payload)
        print(f"       OrderId={order_id}")

        print("[5/6] GET /orders (accept confirmation) ...")
        row = await wait_order(client, order_id)
        print(f"       State={row.get('State')} OrderState={row.get('OrderState')} "
              f"Price={row.get('Price')} OrderQty={row.get('OrderQty')} CumQty={row.get('CumQty')}")
        if float(row.get("CumQty") or 0) > 0:
            print("WARNING: order partially/fully filled (unexpected for far limit) — "
                  "check positions manually")

        print(f"[6/6] PUT /cancelorder {order_id} -> confirm ...")
        await client.cancel_order(order_id)
        for _ in range(10):
            row = await wait_order(client, order_id)
            rec_types = {int(d.get("RecType") or 0) for d in row.get("Details") or []}
            if int(row.get("State") or 0) == 5 or 6 in rec_types:
                print(f"       canceled confirmed: State={row.get('State')} RecTypes={sorted(rec_types)}")
                print("SMOKE TEST PASSED")
                return 0
            await asyncio.sleep(1.0)
        print("WARNING: cancel not confirmed within 10s — check kabu STATION manually")
        return 1
    finally:
        await client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
