from nautilus_trader.adapters.kabu_station.parsing import BoardState, extract_ticks
from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.model.identifiers import InstrumentId


IID = InstrumentId.from_str("7203.XTKS")


def board(px=6000.0, px_time="2026-08-12T09:00:01+09:00", vol=1000.0, b=5999.0, bq=500.0, s=6001.0, sq=400.0):
    return {
        "Symbol": "7203",
        "CurrentPrice": px,
        "CurrentPriceTime": px_time,
        "TradingVolume": vol,
        "Buy1": {"Price": b, "Qty": bq},
        "Sell1": {"Price": s, "Qty": sq},
    }


def test_first_push_emits_quote_only():
    state = BoardState()
    ticks = extract_ticks(board(), state, IID, 1)
    assert len(ticks) == 1
    assert isinstance(ticks[0], QuoteTick)
    assert float(ticks[0].bid_price) == 5999.0  # bid = Buy1 (kabusapi の Bid/Ask 逆転を回避)
    assert float(ticks[0].ask_price) == 6001.0


def test_unchanged_board_emits_nothing():
    state = BoardState()
    extract_ticks(board(), state, IID, 1)
    assert extract_ticks(board(), state, IID, 2) == []


def test_volume_increase_emits_trade_with_delta():
    state = BoardState()
    extract_ticks(board(vol=1000.0), state, IID, 1)
    ticks = extract_ticks(
        board(px=6002.0, px_time="2026-08-12T09:00:02+09:00", vol=1300.0),
        state,
        IID,
        2,
    )
    trades = [t for t in ticks if isinstance(t, TradeTick)]
    assert len(trades) == 1
    assert float(trades[0].price) == 6002.0
    assert float(trades[0].size) == 300.0  # 出来高差分


def test_volume_reset_treated_as_session_start():
    state = BoardState()
    extract_ticks(board(vol=50000.0), state, IID, 1)
    ticks = extract_ticks(
        board(px_time="2026-08-12T12:30:01+09:00", vol=200.0),
        state,
        IID,
        2,
    )
    trades = [t for t in ticks if isinstance(t, TradeTick)]
    assert len(trades) == 1
    assert float(trades[0].size) == 200.0  # 負の差分 -> 当日出来高を数量に


def test_quote_only_change():
    state = BoardState()
    extract_ticks(board(), state, IID, 1)
    ticks = extract_ticks(board(b=6000.0, bq=200.0), state, IID, 2)
    assert len(ticks) == 1
    assert isinstance(ticks[0], QuoteTick)
