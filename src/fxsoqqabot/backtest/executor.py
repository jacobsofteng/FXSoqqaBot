"""BacktestExecutor: fill simulation with session-aware spread, stochastic slippage, and commission.

Does NOT extend PaperExecutor -- separate implementation because PaperExecutor
uses live tick pricing while BacktestExecutor uses bar OHLCV + simulated spread.
Shares the same fill calculation logic pattern.

Key behaviors per plan:
- D-09: Session-aware spread from SpreadModel.sample_spread(hour_utc)
- D-10: Stochastic slippage from SlippageModel.sample_slippage()
- D-11: Commission = volume * commission_per_lot_round_trip

SL/TP checking:
- Buy SL: bar low <= sl_price (worst case for longs)
- Buy TP: bar high >= tp_price (best case for longs)
- Sell SL: bar high >= sl_price (worst case for shorts)
- Sell TP: bar low <= tp_price (best case for shorts)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from fxsoqqabot.backtest.clock import BacktestClock
from fxsoqqabot.backtest.config import BacktestConfig
from fxsoqqabot.backtest.results import TradeRecord


@dataclass
class BacktestPosition:
    """An open position in backtest simulation."""

    ticket: int
    action: str  # "buy" or "sell"
    symbol: str
    volume: float
    entry_price: float
    entry_time: int  # Unix timestamp seconds
    sl_price: float
    tp_price: float | None
    regime: str
    slippage_entry: float
    spread_at_entry: float
    commission: float


class BacktestExecutor:
    """Fill simulation with session-aware spread (D-09), stochastic slippage (D-10), and commission (D-11).

    Does NOT extend PaperExecutor -- separate implementation because PaperExecutor
    uses live tick pricing while BacktestExecutor uses bar OHLCV + simulated spread.
    Shares the same fill calculation logic pattern.
    """

    def __init__(self, config: BacktestConfig, clock: BacktestClock) -> None:
        self._config = config
        self._clock = clock
        self._rng = np.random.default_rng(config.mc_seed)
        self._positions: list[BacktestPosition] = []
        self._closed_trades: list[TradeRecord] = []
        self._equity = config.starting_equity
        self._contract_size = 100.0  # XAUUSD: 1 lot = 100 oz
        self._next_ticket = 2000000

    def _gen_ticket(self) -> int:
        """Generate sequential backtest ticket numbers."""
        ticket = self._next_ticket
        self._next_ticket += 1
        return ticket

    def calculate_commission(self, volume: float) -> float:
        """Calculate round-trip commission for a given lot size.

        Args:
            volume: Position size in lots.

        Returns:
            Commission in account currency.
        """
        return volume * self._config.commission_per_lot_round_trip

    def open_position(
        self,
        action: str,
        volume: float,
        bar: dict,
        sl_distance: float,
        tp_distance: float,
        regime: str,
    ) -> BacktestPosition:
        """Open a position at the current bar's close price + spread + slippage.

        Args:
            action: "buy" or "sell".
            volume: Position size in lots.
            bar: Current bar dict with time, open, high, low, close, volume.
            sl_distance: Stop-loss distance in price units.
            tp_distance: Take-profit distance in price units.
            regime: RegimeState value string at entry.

        Returns:
            The opened BacktestPosition.
        """
        hour_utc = datetime.fromtimestamp(bar["time"], tz=UTC).hour
        spread = self._config.spread_model.sample_spread(hour_utc, self._rng)
        slippage = self._config.slippage_model.sample_slippage(self._rng)

        if action == "buy":
            # Buy at ask + slippage: ask = close + spread
            entry_price = bar["close"] + spread + slippage
            sl_price = entry_price - sl_distance
            tp_price = entry_price + tp_distance if tp_distance > 0 else None
        else:
            # Sell at bid - slippage: bid = close
            entry_price = bar["close"] - slippage
            sl_price = entry_price + sl_distance
            tp_price = entry_price - tp_distance if tp_distance > 0 else None

        commission = self.calculate_commission(volume)
        self._equity -= commission

        position = BacktestPosition(
            ticket=self._gen_ticket(),
            action=action,
            symbol=self._config.symbol,
            volume=volume,
            entry_price=entry_price,
            entry_time=bar["time"],
            sl_price=sl_price,
            tp_price=tp_price,
            regime=regime,
            slippage_entry=slippage,
            spread_at_entry=spread,
            commission=commission,
        )
        self._positions.append(position)
        return position

    def check_sl_tp(self, bar: dict) -> list[TradeRecord]:
        """Check if any open positions hit SL or TP against bar high/low.

        SL checked against bar low for buys (worst case), bar high for sells.
        TP checked against bar high for buys (best case), bar low for sells.

        Args:
            bar: Current bar dict with time, open, high, low, close, volume.

        Returns:
            List of closed TradeRecords.
        """
        closed: list[TradeRecord] = []
        remaining: list[BacktestPosition] = []

        for pos in self._positions:
            exit_price: float | None = None
            exit_reason = ""

            if pos.action == "buy":
                # SL hit if bar low <= sl_price
                if pos.sl_price > 0 and bar["low"] <= pos.sl_price:
                    exit_price = pos.sl_price
                    exit_reason = "sl"
                # TP hit if bar high >= tp_price
                elif pos.tp_price is not None and bar["high"] >= pos.tp_price:
                    exit_price = pos.tp_price
                    exit_reason = "tp"
            else:  # sell
                # SL hit if bar high >= sl_price
                if pos.sl_price > 0 and bar["high"] >= pos.sl_price:
                    exit_price = pos.sl_price
                    exit_reason = "sl"
                # TP hit if bar low <= tp_price
                elif pos.tp_price is not None and bar["low"] <= pos.tp_price:
                    exit_price = pos.tp_price
                    exit_reason = "tp"

            if exit_price is not None:
                # Apply exit slippage
                exit_slippage = self._config.slippage_model.sample_slippage(self._rng)
                if pos.action == "buy":
                    # Closing buy = selling: adverse slippage lowers exit price
                    exit_price -= exit_slippage
                else:
                    # Closing sell = buying: adverse slippage raises exit price
                    exit_price += exit_slippage

                # Compute P&L
                if pos.action == "buy":
                    gross_pnl = (exit_price - pos.entry_price) * pos.volume * self._contract_size
                else:
                    gross_pnl = (pos.entry_price - exit_price) * pos.volume * self._contract_size

                net_pnl = gross_pnl  # Commission already deducted at entry

                record = TradeRecord(
                    entry_time=pos.entry_time,
                    exit_time=bar["time"],
                    action=pos.action,
                    symbol=pos.symbol,
                    volume=pos.volume,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    sl=pos.sl_price,
                    tp=pos.tp_price,
                    pnl=net_pnl,
                    commission=pos.commission,
                    regime=pos.regime,
                    slippage_entry=pos.slippage_entry,
                    slippage_exit=exit_slippage,
                    spread_at_entry=pos.spread_at_entry,
                )
                closed.append(record)
                self._closed_trades.append(record)
                self._equity += net_pnl
            else:
                remaining.append(pos)

        self._positions = remaining
        return closed

    def close_all(self, bar: dict) -> list[TradeRecord]:
        """Force-close all positions at bar close. Used at end of backtest window.

        Args:
            bar: Final bar dict.

        Returns:
            List of closed TradeRecords.
        """
        closed: list[TradeRecord] = []

        for pos in self._positions:
            exit_slippage = self._config.slippage_model.sample_slippage(self._rng)

            if pos.action == "buy":
                # Close buy at bid (= close) - slippage
                exit_price = bar["close"] - exit_slippage
                gross_pnl = (exit_price - pos.entry_price) * pos.volume * self._contract_size
            else:
                # Close sell at ask (= close + spread) + slippage
                hour_utc = datetime.fromtimestamp(bar["time"], tz=UTC).hour
                spread = self._config.spread_model.sample_spread(hour_utc, self._rng)
                exit_price = bar["close"] + spread + exit_slippage
                gross_pnl = (pos.entry_price - exit_price) * pos.volume * self._contract_size

            net_pnl = gross_pnl  # Commission already deducted at entry

            record = TradeRecord(
                entry_time=pos.entry_time,
                exit_time=bar["time"],
                action=pos.action,
                symbol=pos.symbol,
                volume=pos.volume,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                sl=pos.sl_price,
                tp=pos.tp_price,
                pnl=net_pnl,
                commission=pos.commission,
                regime=pos.regime,
                slippage_entry=pos.slippage_entry,
                slippage_exit=exit_slippage,
                spread_at_entry=pos.spread_at_entry,
            )
            closed.append(record)
            self._closed_trades.append(record)
            self._equity += net_pnl

        self._positions = []
        return closed

    @property
    def equity(self) -> float:
        """Current account equity (starting + realized P&L - commissions)."""
        return self._equity

    @property
    def closed_trades(self) -> list[TradeRecord]:
        """All closed trade records."""
        return list(self._closed_trades)
