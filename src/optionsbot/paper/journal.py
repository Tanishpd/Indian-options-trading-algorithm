"""Append-only forward record of what each strategy decided and what it earned.

This is the point of the harness. Five research passes on this project produced
six positive backtest results that dissolved on inspection (docs/10-13), because
a backtest is measured on data that already existed when the rules were written.
A forward record cannot be overfit — the observations do not exist yet.

Design constraints, each because the alternative silently corrupts the evidence:

- **Append-only.** Nothing rewrites history. A strategy that looks bad after
  three months must still look bad in the record.
- **Crash-safe.** Each line is flushed and fsynced before the tick is considered
  recorded, so a killed process loses at most the tick in flight rather than
  truncating the file mid-line.
- **One file per strategy per session-day**, so a corrupt write can never take
  more than a day of one strategy with it.
- **Costs recorded, not just P&L.** Every failure in this project came down to
  costs; a record that omits them cannot diagnose the next one.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True, slots=True)
class Entry:
    """One strategy's state at one tick."""

    ts: datetime
    strategy: str
    index: str
    expiry: date
    spot: float
    phase: str                       # strategy's own phase label
    equity: float                    # cash + marked positions
    cash: float
    realised_costs: float            # cumulative, so cost drag is always visible
    positions: int                   # leg count held
    orders: list[dict] = field(default_factory=list)   # orders emitted this tick
    fills: list[dict] = field(default_factory=list)    # fills that resulted
    note: str = ""

    def to_json(self) -> str:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        d["expiry"] = self.expiry.isoformat()
        return json.dumps(d, separators=(",", ":"), sort_keys=True)


class Journal:
    """Append-only JSONL writer, one file per strategy per day."""

    def __init__(self, root: Path, strategy: str, day: date) -> None:
        self.path = Path(root) / strategy / f"{day.isoformat()}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = None

    def append(self, entry: Entry) -> None:
        if self._fh is None:
            self._fh = open(self.path, "a", buffering=1)
        self._fh.write(entry.to_json() + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())      # survive a hard kill, not just an exit

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "Journal":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read(root: Path, strategy: str | None = None) -> Iterator[dict]:
    """Every recorded entry, oldest first.

    A truncated final line — the one case a hard kill can still produce — is
    skipped rather than raising, because losing one tick must not make the whole
    forward record unreadable.
    """
    root = Path(root)
    dirs = [root / strategy] if strategy else sorted(
        p for p in root.iterdir() if p.is_dir()
    ) if root.exists() else []
    for d in dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.jsonl")):
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue          # truncated tail of a killed process


def strategies(root: Path) -> list[str]:
    root = Path(root)
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())
