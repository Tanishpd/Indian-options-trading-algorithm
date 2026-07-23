"""Nifty 200 point-in-time reconstruction. The parser is pinned on a realistic
press-release fixture; the backward walk is pinned on a hand-worked example.
"""
from datetime import date

from optionsbot.data.nifty_membership import parse_nifty200_pr, reconstruct

# Shaped exactly like a real NSE "Replacements in indices" release (the parser
# was validated against the genuine Sept-2024 PDF too).
PR = """
These changes shall become effective from September 30, 2024 (close of September 27, 2024).

l)    Nifty 200

The following companies are being excluded:

   Sr. No.   Company Name                Symbol
     1       Berger Paints India Ltd.    BERGEPAINT
     2       Gland Pharma Ltd.           GLAND

The following companies are being included:

   Sr. No.   Company Name                Symbol
     1       Bharti Hexacom Ltd.         BHARTIHEXA
     2       Hindustan Zinc Ltd.         HINDZINC

m) Nifty LargeMidcap 250

The following companies are being excluded:
     1       Something Else Ltd.         NOTNIFTY200
"""


def test_parse_pr_extracts_date_and_symbols_for_nifty200_only():
    eff, incl, excl = parse_nifty200_pr(PR)
    assert eff == date(2024, 9, 30)
    assert incl == frozenset({"BHARTIHEXA", "HINDZINC"})
    assert excl == frozenset({"BERGEPAINT", "GLAND"})
    assert "NOTNIFTY200" not in (incl | excl)         # bled from the next index -> excluded


def test_reconstruct_walks_backward_from_the_anchor():
    """Two reviews. Anchor is today's list. Undoing each review in reverse must
    restore the earlier membership."""
    anchor = frozenset({"A", "B", "NEW2", "NEW1"})
    reviews = [
        # Mar 2024: OLD1 left, NEW1 joined
        (date(2024, 3, 30), frozenset({"NEW1"}), frozenset({"OLD1"})),
        # Sep 2024: OLD2 left, NEW2 joined
        (date(2024, 9, 30), frozenset({"NEW2"}), frozenset({"OLD2"})),
    ]
    snaps = reconstruct(anchor, reviews)
    m = dict(snaps)
    # From Sep 2024 onward: the anchor.
    assert m[date(2024, 9, 30)] == anchor
    # Between Mar and Sep 2024: undo Sep -> NEW2 not yet in, OLD2 still in.
    assert m[date(2024, 3, 30)] == frozenset({"A", "B", "NEW1", "OLD2"})
    # ascending
    assert [d for d, _ in snaps] == [date(2024, 3, 30), date(2024, 9, 30)]


def test_reconstruct_empty_reviews_is_just_the_anchor_undated():
    # With no reviews we cannot date anything; the schedule is empty and the
    # backtest falls back to the full universe (labelled survivorship-biased).
    assert reconstruct(frozenset({"A", "B"}), []) == []
