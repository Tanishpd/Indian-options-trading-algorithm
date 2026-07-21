"""Bhavcopy ingester. Fixtures are verbatim rows from the real 2026-07-17
NSE and BSE UDiFF files, so the parser is pinned to the actual schema."""
import io
import zipfile
from datetime import date

import pytest

from optionsbot.data import bhavcopy as bc
from optionsbot.instruments import Right

HEADER = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
    "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,"
    "TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4"
)


def row(sym="NIFTY", tp="IDO", strike="24500.00", opt="CE", close="60.00",
        settle="61.00", vol="1000", oi="500", lot="65", expiry="2026-07-21"):
    return (
        f"2026-07-17,2026-07-17,FO,NSE,{tp},12345,,{sym},,{expiry},{expiry},"
        f"{strike},{opt},NIFTY,59.00,62.00,58.00,{close},{close},59.00,24334.30,"
        f"{settle},{oi},0,{vol},1000000,50,F1,{lot},,,,,"
    )


def csv_bytes(*rows):
    body = "\n".join([HEADER, *rows]) + "\n"
    return (body + " " * 25_000).encode()      # pad past the size guard


def zip_bytes(*rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BhavCopy.csv", csv_bytes(*rows).decode())
    return buf.getvalue()


def test_parses_a_real_schema_row():
    rows = bc._rows_from_bytes(csv_bytes(row()), "u")
    r = bc._parse(rows[0], "NIFTY")
    assert r.day == date(2026, 7, 17) and r.expiry == date(2026, 7, 21)
    assert r.strike == 24500.0 and r.right is Right.CALL
    assert r.close == 60.0 and r.settlement == 61.0
    assert r.volume == 1000 and r.open_interest == 500 and r.lot_size == 65
    assert r.underlying == 24334.30


def test_ignores_other_symbols_and_futures():
    assert bc._parse(bc._rows_from_bytes(csv_bytes(row(sym="BANKNIFTY")), "u")[0], "NIFTY") is None
    assert bc._parse(bc._rows_from_bytes(csv_bytes(row(tp="IDF", opt="")), "u")[0], "NIFTY") is None


def test_untraded_rows_are_dropped_by_default(monkeypatch):
    blob = zip_bytes(row(strike="24500.00", vol="1000"),
                     row(strike="25850.00", close="111.05", settle="54.10", vol="0", oi="0"))
    monkeypatch.setattr(bc, "_fetch", lambda url, timeout=120: blob)

    traded = bc.fetch_day("NIFTY", date(2026, 7, 17))
    assert [r.strike for r in traded] == [24500.0]          # phantom row dropped

    everything = bc.fetch_day("NIFTY", date(2026, 7, 17), traded_only=False)
    assert len(everything) == 2
    phantom = next(r for r in everything if r.strike == 25850.0)
    # The real trap: a close of 111.05 on a contract that never traded, whose
    # settlement was 54.10 — a 2x error if used as a fill price.
    assert phantom.traded is False
    assert phantom.last_traded is None                       # not achievable
    assert phantom.mark == 54.10                             # settlement instead
    assert phantom.close == 111.05                           # raw value still visible


def test_traded_row_exposes_both_prices():
    r = bc._parse(bc._rows_from_bytes(csv_bytes(row(close="875.20", settle="1611.75")), "u")[0], "NIFTY")
    assert r.last_traded == 875.20      # achievable
    assert r.mark == 1611.75            # exchange valuation; they disagree by 84%


def test_bse_html_shell_is_not_mistaken_for_data():
    shell = b"<!DOCTYPE html><html><body>app shell</body></html>"
    with pytest.raises(bc.NoDataForDate, match="not a bhavcopy"):
        bc._rows_from_bytes(shell, "bse-url")


def test_short_body_rejected_even_if_csv_shaped():
    with pytest.raises(bc.NoDataForDate, match="not a bhavcopy"):
        bc._rows_from_bytes((HEADER + "\n").encode(), "u")


def test_pre_nov_2024_dates_refused(monkeypatch):
    monkeypatch.setattr(bc, "_fetch", lambda url, timeout=120: zip_bytes(row()))
    with pytest.raises(ValueError, match="pre-Nov-2024"):
        bc.fetch_day("NIFTY", date(2024, 6, 3))


def test_universe_locked(monkeypatch):
    monkeypatch.setattr(bc, "_fetch", lambda url, timeout=120: zip_bytes(row()))
    with pytest.raises(ValueError, match="permitted universe"):
        bc.fetch_day("BANKNIFTY", date(2026, 7, 17))


def test_day_with_no_matching_rows_raises(monkeypatch):
    monkeypatch.setattr(bc, "_fetch", lambda url, timeout=120: zip_bytes(row(sym="BANKNIFTY")))
    with pytest.raises(bc.NoDataForDate, match="no NIFTY option rows"):
        bc.fetch_day("NIFTY", date(2026, 7, 17))


def test_csv_roundtrip(tmp_path):
    rows = [bc._parse(bc._rows_from_bytes(csv_bytes(row()), "u")[0], "NIFTY")]
    p = tmp_path / "out.csv"
    bc.write_csv(rows, p)
    assert bc.read_csv(p) == rows


def test_daterange_skips_weekends():
    days = list(bc.daterange(date(2026, 7, 17), date(2026, 7, 21)))   # Fri..Tue
    assert days == [date(2026, 7, 17), date(2026, 7, 20), date(2026, 7, 21)]
