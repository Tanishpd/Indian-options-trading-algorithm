"""Performance metrics. Max drawdown is the first-class metric of this project."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Sequence


def max_drawdown(equity: Sequence[float]) -> float:
    """Largest peak-to-trough decline, in rupees (>= 0)."""
    peak = float("-inf")
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        worst = max(worst, peak - value)
    return worst


@dataclass
class BacktestReport:
    start_capital: float
    equity_curve: list[tuple[date, float]] = field(default_factory=list)
    trade_pnls: list[float] = field(default_factory=list)
    total_costs: float = 0.0
    halted: bool = False
    halt_reason: str | None = None
    unquoted_orders: int = 0   # orders whose leg had no bar that day (silent in v0)
    unfilled_orders: int = 0   # limit orders the bar never touched
    open_positions_end: int = 0  # positions still open when the run ended

    @property
    def end_equity(self) -> float:
        return self.equity_curve[-1][1] if self.equity_curve else self.start_capital

    @property
    def net_pnl(self) -> float:
        return self.end_equity - self.start_capital

    @property
    def net_return_pct(self) -> float:
        return 100.0 * self.net_pnl / self.start_capital

    @property
    def max_drawdown_rupees(self) -> float:
        # Starting capital is the first peak: dipping below start is a real drawdown.
        return max_drawdown([self.start_capital, *(v for _, v in self.equity_curve)])

    @property
    def cost_drag_pct(self) -> float:
        return 100.0 * self.total_costs / self.start_capital

    @property
    def worst_trade(self) -> float:
        return min(self.trade_pnls) if self.trade_pnls else 0.0
