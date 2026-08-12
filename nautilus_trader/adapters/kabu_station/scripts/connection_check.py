"""
kabu STATION 疎通確認 (実注文なし): トークン -> ソフトリミット -> 余力 -> 板 -> PUSH 30秒。

前提: kabu STATION 起動済み (同一 PC)、検証環境ポート 18081 (本番は --production)。
実行: op run --env-file=.env.1password -- python -m nautilus_trader.adapters.kabu_station.scripts.connection_check [--production] [--symbol 7203]
"""

import argparse
import asyncio
import os

from nautilus_trader.adapters.kabu_station.http.client import KabuStationHttpClient
from nautilus_trader.adapters.kabu_station.parsing import BoardState, extract_ticks
from nautilus_trader.adapters.kabu_station.websocket.client import KabuStationWebSocketClient
from nautilus_trader.model.identifiers import InstrumentId


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--production", action="store_true")
    p.add_argument("--symbol", default="7203")
    args = p.parse_args()
    port = 18080 if args.production else 18081
    env = "production" if args.production else "practice"

    client = KabuStationHttpClient(
        api_password=os.environ["KABU_STATION_API_PASSWORD"],
        base_url=f"http://localhost:{port}/kabusapi",
    )
    print(f"[1/5] token ({env}) ...")
    await client.get_token()
    print("      OK")
    print("[2/5] /apisoftlimit ...")
    print("      ", await client.get_soft_limit())
    print("[3/5] /wallet/cash ...")
    wallet = await client.get_wallet_cash()
    print(f"       StockAccountWallet = {wallet.get('StockAccountWallet')}")
    print(f"[4/5] /board/{args.symbol}@1 ...")
    board = await client.get_board(args.symbol)
    print(f"       CurrentPrice = {board.get('CurrentPrice')}")
    print(f"[5/5] PUSH 30s ({args.symbol}) ...")
    await client.register_symbols([args.symbol])
    state = BoardState()
    iid = InstrumentId.from_str(f"{args.symbol}.XTKS")
    count = 0

    def on_push(msg: dict) -> None:
        nonlocal count
        for tick in extract_ticks(msg, state, iid, 0):
            count += 1
            if count <= 5:
                print(f"       {tick}")

    ws = KabuStationWebSocketClient(f"ws://localhost:{port}/kabusapi/websocket", on_push)
    ws.start(asyncio.get_running_loop())
    await asyncio.sleep(30)
    await ws.stop()
    await client.unregister_symbols([args.symbol])
    await client.aclose()
    print(f"done: {count} ticks received")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
