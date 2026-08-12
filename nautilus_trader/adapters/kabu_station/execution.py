import asyncio
import datetime as dt

from nautilus_trader.adapters.kabu_station.config import KabuStationExecClientConfig
from nautilus_trader.adapters.kabu_station.constants import (
    DETAIL_STATE_ERROR,
    KABU,
    KABU_VENUE,
    REC_TYPE_CANCELED,
    REC_TYPE_EXPIRED,
    REC_TYPE_FILLED,
    REC_TYPE_REVOKED,
    SIDE_BUY,
)
from nautilus_trader.adapters.kabu_station.http.client import KabuStationHttpClient
from nautilus_trader.adapters.kabu_station.http.errors import KabuStationApiError
from nautilus_trader.adapters.kabu_station.parsing import build_sendorder, updtime_cursor
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import CancelOrder, ModifyOrder, SubmitOrder
from nautilus_trader.execution.reports import OrderStatusReport
from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.model.currencies import JPY
from nautilus_trader.model.enums import (
    AccountType,
    ContingencyType,
    LiquiditySide,
    OmsType,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientId,
    ClientOrderId,
    InstrumentId,
    TradeId,
    VenueOrderId,
)
from nautilus_trader.model.objects import AccountBalance, Money, Price, Quantity


class KabuStationExecutionClient(LiveExecutionClient):
    """
    kabu STATION 発注クライアント。

    - 注文イベント PUSH は存在しない -> /orders を 1 秒間隔でポーリング
      (updtime = 現在時刻 - 30 秒、ExecutionID で重複排除)
    - 訂正 API なし -> modify は拒否 (cancel + resubmit)
    - `trading_enabled=False` (既定) の間はすべての発注を拒否
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client: KabuStationHttpClient,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        instrument_provider: InstrumentProvider,
        config: KabuStationExecClientConfig,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=ClientId(KABU),
            venue=KABU_VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=JPY,
            instrument_provider=instrument_provider,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
        self._client = client
        self._config_kabu = config
        self._account_id = AccountId(f"{KABU}-001")
        self._set_account_id(self._account_id)
        self._seen_exec_ids: set[str] = set()
        self._poll_task: asyncio.Task | None = None

    async def _connect(self) -> None:
        await self._client.get_token()
        try:
            limit = await self._client.get_soft_limit()
            self._log.info(f"kabusapi soft limits: {limit}")
        except KabuStationApiError as e:
            self._log.warning(f"soft limit query failed: {e}")
        await self._update_account_state()
        self._poll_task = self._loop.create_task(self._poll_orders_loop())

    async def _disconnect(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
        await self._client.aclose()

    async def _update_account_state(self) -> None:
        wallet = await self._client.get_wallet_cash()
        cash = float(wallet.get("StockAccountWallet") or 0.0)
        balance = AccountBalance(
            total=Money(cash, JPY),
            locked=Money(0, JPY),
            free=Money(cash, JPY),
        )
        self.generate_account_state(
            balances=[balance],
            margins=[],
            reported=True,
            ts_event=self._clock.timestamp_ns(),
        )

    # --- order entry -----------------------------------------------------

    async def _open_position_qtys(self, symbol: str) -> tuple[int, int]:
        long_qty = short_qty = 0
        for pos in await self._client.get_positions():
            if str(pos.get("Symbol")) != symbol:
                continue
            qty = int(float(pos.get("LeavesQty") or 0))
            if str(pos.get("Side")) == SIDE_BUY:
                long_qty += qty
            else:
                short_qty += qty
        return long_qty, short_qty

    async def _submit_order(self, command: SubmitOrder) -> None:
        order = command.order
        self.generate_order_submitted(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            ts_event=self._clock.timestamp_ns(),
        )
        if not self._config_kabu.trading_enabled:
            self.generate_order_rejected(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                reason="trading_enabled=False (set KabuStationExecClientConfig.trading_enabled=True)",
                ts_event=self._clock.timestamp_ns(),
            )
            return
        try:
            open_long, open_short = (0, 0)
            if self._config_kabu.use_margin:
                open_long, open_short = await self._open_position_qtys(
                    order.instrument_id.symbol.value,
                )
            payload = build_sendorder(
                order,
                open_long=open_long,
                open_short=open_short,
                use_margin=self._config_kabu.use_margin,
                exchange=self._config_kabu.exchange,
                account_type=self._config_kabu.account_type,
                margin_trade_type=self._config_kabu.margin_trade_type,
            )
            venue_order_id = await self._client.send_order(payload)
        except (ValueError, KabuStationApiError) as e:
            self.generate_order_rejected(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                reason=str(e),
                ts_event=self._clock.timestamp_ns(),
            )
            return
        self.generate_order_accepted(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            venue_order_id=VenueOrderId(venue_order_id),
            ts_event=self._clock.timestamp_ns(),
        )

    async def _cancel_order(self, command: CancelOrder) -> None:
        venue_order_id = command.venue_order_id or self._cache.venue_order_id(
            command.client_order_id,
        )
        if venue_order_id is None:
            self._log.error(f"Cannot cancel {command.client_order_id}: no venue order id")
            return
        try:
            await self._client.cancel_order(venue_order_id.value)
        except KabuStationApiError as e:
            self.generate_order_cancel_rejected(
                strategy_id=command.strategy_id,
                instrument_id=command.instrument_id,
                client_order_id=command.client_order_id,
                venue_order_id=venue_order_id,
                reason=str(e),
                ts_event=self._clock.timestamp_ns(),
            )
        # 取消成功の確定イベントはポーリングで生成する

    async def _modify_order(self, command: ModifyOrder) -> None:
        self.generate_order_modify_rejected(
            strategy_id=command.strategy_id,
            instrument_id=command.instrument_id,
            client_order_id=command.client_order_id,
            venue_order_id=command.venue_order_id,
            reason="kabusapi has no modify API: cancel and resubmit",
            ts_event=self._clock.timestamp_ns(),
        )

    # --- order event polling ---------------------------------------------

    async def _poll_orders_loop(self) -> None:
        while True:
            try:
                cursor = updtime_cursor(dt.datetime.now())
                rows = await self._client.get_orders(updtime=cursor)
                for row in rows:
                    self._process_order_row(row)
            except asyncio.CancelledError:
                return
            except Exception as e:
                self._log.warning(f"order polling error: {e}")
            await asyncio.sleep(self._config_kabu.poll_interval_secs)

    def _process_order_row(self, row: dict) -> None:
        venue_order_id = VenueOrderId(str(row.get("ID")))
        client_order_id = self._cache.client_order_id(venue_order_id)
        if client_order_id is None:
            return  # このノード以外から発注された注文
        order = self._cache.order(client_order_id)
        if order is None:
            return
        instrument = self._cache.instrument(order.instrument_id)
        ts = self._clock.timestamp_ns()
        details = row.get("Details") or []
        for d in details:
            rec_type = int(d.get("RecType") or 0)
            exec_id = d.get("ExecutionID")
            if rec_type == REC_TYPE_FILLED and exec_id and exec_id not in self._seen_exec_ids:
                self._seen_exec_ids.add(exec_id)
                self.generate_order_filled(
                    strategy_id=order.strategy_id,
                    instrument_id=order.instrument_id,
                    client_order_id=client_order_id,
                    venue_order_id=venue_order_id,
                    venue_position_id=None,
                    trade_id=TradeId(str(exec_id)),
                    order_side=order.side,
                    order_type=order.order_type,
                    last_qty=instrument.make_qty(float(d.get("Qty") or 0)),
                    last_px=instrument.make_price(float(d.get("Price") or 0)),
                    quote_currency=JPY,
                    commission=Money(0, JPY),  # kabusapi は約定単位の手数料を返さない
                    liquidity_side=LiquiditySide.NO_LIQUIDITY_SIDE,
                    ts_event=ts,
                )
        state = int(row.get("State") or 0)
        cum = float(row.get("CumQty") or 0)
        qty = float(row.get("OrderQty") or 0)
        if state == 5 and cum < qty and order.is_open:
            rec_types = {int(d.get("RecType") or 0) for d in details}
            error_detail = any(int(d.get("State") or 0) == DETAIL_STATE_ERROR for d in details)
            if error_detail:
                self.generate_order_rejected(
                    strategy_id=order.strategy_id,
                    instrument_id=order.instrument_id,
                    client_order_id=client_order_id,
                    reason="kabusapi detail state 4 (error)",
                    ts_event=ts,
                )
            elif rec_types & {REC_TYPE_EXPIRED, REC_TYPE_REVOKED}:
                self.generate_order_expired(
                    strategy_id=order.strategy_id,
                    instrument_id=order.instrument_id,
                    client_order_id=client_order_id,
                    venue_order_id=venue_order_id,
                    ts_event=ts,
                )
            elif REC_TYPE_CANCELED in rec_types:
                self.generate_order_canceled(
                    strategy_id=order.strategy_id,
                    instrument_id=order.instrument_id,
                    client_order_id=client_order_id,
                    venue_order_id=venue_order_id,
                    ts_event=ts,
                )

    # --- reconciliation ---------------------------------------------------

    def _report_from_row(self, row: dict) -> OrderStatusReport | None:
        symbol = str(row.get("Symbol"))
        iid = InstrumentId.from_str(f"{symbol}.{KABU_VENUE}")
        state = int(row.get("State") or 0)
        cum = float(row.get("CumQty") or 0)
        qty = float(row.get("OrderQty") or 0)
        if state == 5:
            status = OrderStatus.FILLED if cum >= qty and qty > 0 else OrderStatus.CANCELED
        elif cum > 0:
            status = OrderStatus.PARTIALLY_FILLED
        else:
            status = OrderStatus.ACCEPTED
        price_val = float(row.get("Price") or 0)
        ts = self._clock.timestamp_ns()
        venue_order_id = VenueOrderId(str(row.get("ID")))
        client_order_id = self._cache.client_order_id(venue_order_id) or ClientOrderId(
            str(UUID4()),
        )
        return OrderStatusReport(
            account_id=self._account_id,
            instrument_id=iid,
            client_order_id=client_order_id,
            order_list_id=None,
            venue_order_id=venue_order_id,
            order_side=OrderSide.BUY if str(row.get("Side")) == SIDE_BUY else OrderSide.SELL,
            order_type=OrderType.LIMIT if price_val > 0 else OrderType.MARKET,
            contingency_type=ContingencyType.NO_CONTINGENCY,
            time_in_force=TimeInForce.DAY,
            order_status=status,
            price=Price(price_val, 1) if price_val > 0 else None,
            avg_px=None,
            quantity=Quantity(qty, 0),
            filled_qty=Quantity(cum, 0),
            ts_accepted=ts,
            ts_last=ts,
            report_id=UUID4(),
            ts_init=ts,
        )

    async def generate_order_status_reports(self, command) -> list[OrderStatusReport]:
        reports = []
        try:
            for row in await self._client.get_orders():
                report = self._report_from_row(row)
                if report is not None:
                    reports.append(report)
        except KabuStationApiError as e:
            self._log.error(f"generate_order_status_reports failed: {e}")
        return reports

    async def generate_fill_reports(self, command) -> list:
        return []  # 約定明細はポーリングで処理 (別途 FillReport 生成は今後の課題)

    async def generate_position_status_reports(self, command) -> list:
        return []
