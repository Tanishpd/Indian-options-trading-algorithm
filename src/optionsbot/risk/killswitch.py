"""Portfolio kill-switch — the drawdown cap made executable (docs/04).

A deliberate plain class (not a dataclass): safety state must not be
clonable/resettable via dataclasses.replace, and equality/repr must not
pretend a halted switch equals an armed one. Once tripped, the switch can
never re-arm itself: re-arming requires an explicit operator identifier.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from ..config import RiskConfig


class KillSwitch:
    def __init__(
        self,
        risk: RiskConfig,
        alert: Callable[[str], None] | None = None,
        start_equity: float | None = None,
    ) -> None:
        """`start_equity` seeds the peak and daily baseline so first-day losses
        count against the caps. Without it, the baseline is the first observed
        equity — acceptable only when observations start at true capital."""
        self.risk = risk
        self.alert = alert
        self.halt_reason: str | None = None
        self._halted = False
        # Seeding at construction makes first-day losses count against the caps.
        self._peak: float | None = start_equity
        self._day: date | None = None
        self._day_start: float | None = None
        self._last: float | None = start_equity

    @property
    def halted(self) -> bool:
        return self._halted

    def update(self, day: date, equity: float) -> None:
        """Feed one equity observation (engine calls this at each mark-to-market).

        Daily-loss granularity follows the observation cadence: close-to-close
        with daily bars, tighter as intraday observations arrive.
        """
        if self._halted:
            return
        if self._peak is None:
            self._peak = equity
        if self._last is None:  # first observation, or first after a re-arm
            self._last = equity
        if day != self._day:
            self._day = day
            self._day_start = self._last
        self._last = equity
        self._peak = max(self._peak, equity)

        drawdown = self._peak - equity
        if drawdown >= self.risk.max_drawdown_rupees:
            self.trip(
                f"max drawdown breached: Rs {drawdown:,.2f} from peak "
                f"Rs {self._peak:,.2f} (cap Rs {self.risk.max_drawdown_rupees:,.2f})"
            )
            return
        assert self._day_start is not None
        day_loss = self._day_start - equity
        if day_loss >= self.risk.daily_loss_limit_rupees:
            self.trip(
                f"daily loss limit breached: Rs {day_loss:,.2f} on {day} "
                f"(limit Rs {self.risk.daily_loss_limit_rupees:,.2f})"
            )

    def trip(self, reason: str) -> None:
        """Halt trading. Public so the engine can trip on risk-invariant breaches
        (naked book, per-trade cap) through the same alert/halt machinery."""
        if self._halted:
            return
        self._halted = True
        self.halt_reason = reason
        if self.alert is not None:
            self.alert(reason)

    def snapshot(self) -> dict:
        """Serializable state for session persistence (paper/live restarts)."""
        return {
            "halted": self._halted,
            "halt_reason": self.halt_reason,
            "peak": self._peak,
            "day": self._day.isoformat() if self._day else None,
            "day_start": self._day_start,
            "last": self._last,
        }

    def restore(self, state: dict) -> None:
        """Restore from snapshot(). A halted switch stays halted across restarts."""
        self._halted = state["halted"]
        self.halt_reason = state["halt_reason"]
        self._peak = state["peak"]
        self._day = date.fromisoformat(state["day"]) if state["day"] else None
        self._day_start = state["day_start"]
        self._last = state["last"]

    def rearm(self, operator: str, reset_peak: bool = False) -> None:
        """Manual re-arm only. `operator` is a required audit string."""
        if not operator or not operator.strip():
            raise ValueError("re-arming requires an operator identifier (manual action)")
        self._halted = False
        self.halt_reason = None
        self._day = None
        self._day_start = None
        self._last = None  # fresh daily baseline from the next observation
        if reset_peak:
            self._peak = None
