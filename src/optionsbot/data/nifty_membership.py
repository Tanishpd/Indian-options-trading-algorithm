"""Reconstruct point-in-time Nifty 200 membership from NSE's own primary data.

The momentum backtest needs to know which stocks were in the index on each past
date, or its result is survivorship-biased (docs/14). NSE does not publish that
schedule directly, but it is reconstructable — for free — from two primary
sources plus today's list:

  - the current 200-name constituent CSV (the anchor to walk back from), and
  - the semi-annual "Replacements in indices" press releases, each of which
    lists, symbol by symbol, the companies included in and excluded from the
    Nifty 200 at that review, with the effective date.

This module is the pure, testable core: parse one press release, and walk
backward from the anchor applying each review in reverse to snapshot membership
at every review date. Fetching the PDFs is the driver's job.
"""
from __future__ import annotations

import re
from datetime import date

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}


def _parse_effective(text: str) -> date | None:
    """The rebalance effective date, e.g. 'effective from September 30, 2024'."""
    m = re.search(r"effective from\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", text)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower())
    return date(int(m.group(3)), mon, int(m.group(2))) if mon else None


def _nifty200_section(text: str) -> str:
    """The slice of the release covering the Nifty 200, up to the next index."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        # a header line ending in "Nifty 200" (optionally lettered "l)  Nifty 200")
        if re.search(r"\bNifty\s*200\s*$", ln.strip()):
            start = i
            break
    if start is None:
        return ""
    out = []
    for ln in lines[start + 1:]:
        # Stop at the next enumerated section header. NSE numbers them "12) Nifty
        # 200", "13) Nifty LargeMidcap 250" — number OR letter, then ")". A
        # constituent row ("1  ACC Ltd. ACC") has no paren, so it never matches.
        if re.match(r"\s*(\d+|[a-zA-Z])\)\s", ln):
            break
        out.append(ln)
    return "\n".join(out)


def _symbols(block: str) -> frozenset[str]:
    """The last token of each numbered row is the NSE symbol."""
    out = set()
    for ln in block.splitlines():
        if not re.match(r"\s*\d+\s", ln):          # numbered constituent rows only
            continue
        tok = ln.split()[-1]
        if re.fullmatch(r"[A-Z0-9&.-]{1,20}", tok):
            out.add(tok)
    return frozenset(out)


def parse_nifty200_pr(text: str) -> tuple[date | None, frozenset[str], frozenset[str]]:
    """(effective_date, included, excluded) for the Nifty 200 from one release."""
    eff = _parse_effective(text)
    sec = _nifty200_section(text)
    excl_block, incl_block = "", ""
    low = sec.lower()
    ei, ii = low.find("excluded"), low.find("included")
    if ei != -1:
        excl_block = sec[ei: ii if 0 <= ii else len(sec)]
    if ii != -1:
        incl_block = sec[ii:]
    return eff, _symbols(incl_block), _symbols(excl_block)


def reconstruct(anchor: frozenset[str],
                reviews: list[tuple[date, frozenset[str], frozenset[str]]]
                ) -> list[tuple[date, frozenset[str]]]:
    """Point-in-time snapshots, walking backward from today's list.

    `anchor` is the current membership (valid from the newest review onward).
    `reviews` is (effective_date, included, excluded) per review. At a review,
    the included joined and the excluded left, so membership BEFORE it is
    `after - included + excluded`. Snapshotting each `after` set at its own
    effective date yields the schedule `momentum.backtest(membership=...)` wants.
    Days before the earliest review have no snapshot — the backtest falls back to
    the full universe there and labels it survivorship-biased."""
    snaps: list[tuple[date, frozenset[str]]] = []
    current = anchor
    for eff, incl, excl in sorted(reviews, key=lambda r: r[0], reverse=True):
        snaps.append((eff, current))              # membership effective from `eff`
        current = (current - incl) | excl         # undo the review -> prior membership
    snaps.sort()
    return snaps
