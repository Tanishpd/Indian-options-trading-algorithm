"""Build a point-in-time Nifty 200 membership schedule from NSE primary sources.

    python -m optionsbot.data.fetch_nifty_membership data/nifty200_pit --back-to 2019

Downloads today's 200-name list (the anchor) and the semi-annual "Replacements
in indices" press releases (probing the publish dates, which vary), reconstructs
membership backward, and writes dated `YYYY-MM-DD.txt` snapshots that
`equity.load_membership` / `momentum.backtest(membership=...)` read. This is the
free route to killing survivorship bias (docs/14). Days before the earliest
review found have no snapshot — the backtest falls back to the full universe and
labels it.
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from .nifty_membership import parse_nifty200_pr, reconstruct

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
ANCHOR_URL = "https://niftyindices.com/IndexConstituent/ind_nifty200list.csv"
PR_URL = "https://www.niftyindices.com/Press_Release/ind_prs{ddmmyyyy}.pdf"


def _get(url: str, timeout: int = 60) -> bytes | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA, "Referer": "https://www.niftyindices.com/"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            blob = r.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    return blob


def _anchor() -> frozenset[str]:
    blob = _get(ANCHOR_URL)
    if not blob:
        raise SystemExit(f"could not download the anchor list: {ANCHOR_URL}")
    rows = csv.DictReader(io.StringIO(blob.decode("utf-8", "replace")))
    syms = {(r.get("Symbol") or "").strip().upper()
            for r in rows if (r.get("Symbol") or "").strip()}
    if len(syms) < 150:
        raise SystemExit(f"anchor list looks wrong: {len(syms)} symbols")
    return frozenset(syms)


def _pdf_text(blob: bytes) -> str:
    """pdftotext -layout if available (best), else a crude byte-strip fallback."""
    import shutil
    import subprocess
    import tempfile

    if blob[:4] != b"%PDF":
        return ""                                  # a soft-404 HTML page, not a PDF
    if shutil.which("pdftotext"):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as fh:
            fh.write(blob); fh.flush()
            out = subprocess.run(["pdftotext", "-layout", fh.name, "-"],
                                 capture_output=True)
            return out.stdout.decode("utf-8", "replace")
    return blob.decode("latin-1", "replace")


def _find_reviews(back_to: int, log) -> list[tuple[date, frozenset[str], frozenset[str]]]:
    """Probe the publish-date windows (releases land ~4 weeks before each Mar and
    Sep rebalance) and parse whichever PDFs exist."""
    reviews = []
    this_year = date.today().year
    for year in range(this_year, back_to - 1, -1):
        for month, days in ((2, range(15, 32)), (3, range(1, 12)),
                            (8, range(15, 32)), (9, range(1, 8))):
            for d in days:
                try:
                    when = date(year, month, d)
                except ValueError:
                    continue
                if when > date.today():
                    continue
                blob = _get(PR_URL.format(ddmmyyyy=when.strftime("%d%m%Y")))
                if not blob:
                    continue
                eff, incl, excl = parse_nifty200_pr(_pdf_text(blob))
                if not (eff and (incl or excl)):
                    continue
                if len(incl) > 40 or len(excl) > 40:
                    log(f"  {when} -> SKIPPED (parsed +{len(incl)} -{len(excl)}, "
                        "implausible for a Nifty 200 review — layout not handled)")
                    break
                reviews.append((eff, incl, excl))
                log(f"  {when} -> review effective {eff}: +{len(incl)} -{len(excl)}")
                break                              # one release per window
    return reviews


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out", type=Path, help="dir for YYYY-MM-DD.txt snapshots")
    ap.add_argument("--back-to", type=int, default=2019,
                    help="earliest year of press releases to probe")
    args = ap.parse_args(argv)

    anchor = _anchor()
    print(f"anchor: {len(anchor)} current Nifty 200 symbols")
    reviews = _find_reviews(args.back_to, log=print)
    if not reviews:
        print("no press releases found — cannot build a schedule", file=sys.stderr)
        return 1
    snaps = reconstruct(anchor, reviews)

    args.out.mkdir(parents=True, exist_ok=True)
    for eff, members in snaps:
        (args.out / f"{eff.isoformat()}.txt").write_text(
            "# Nifty 200 point-in-time membership, reconstructed from NSE\n"
            + "\n".join(sorted(members)) + "\n")
    print(f"wrote {len(snaps)} snapshots ({snaps[0][0]} .. {snaps[-1][0]}) "
          f"to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
