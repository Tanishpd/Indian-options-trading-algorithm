from datetime import date

import pytest

import optionsbot.feed.angelone as angelone_mod
from optionsbot.feed.angelone import AngelOneFeed
from optionsbot.instruments import Right

EXPIRY = date(2026, 7, 14)


def master_row(strike_rupees, right, token, expiry="14JUL2026"):
    return {
        "exch_seg": "NFO", "name": "NIFTY", "instrumenttype": "OPTIDX",
        "expiry": expiry, "symbol": f"NIFTY{expiry}{int(strike_rupees)}{right}",
        "strike": f"{strike_rupees * 100:.6f}", "token": token, "lotsize": "65",
    }


SPOT_ROW = {"exch_seg": "NSE", "symbol": "Nifty 50", "token": "26000", "name": "NIFTY"}


class FakeClient:
    def __init__(self, quotes):
        self.quotes = quotes          # token -> quote item
        self.batches = []

    def getMarketData(self, mode, exchange_tokens):
        assert mode == "FULL"
        (_, tokens), = exchange_tokens.items()
        self.batches.append(list(tokens))
        return {
            "status": True,
            "data": {"fetched": [self.quotes[t] for t in tokens if t in self.quotes]},
        }


def quote_item(token, ltp, bid=None, ask=None):
    depth = {"buy": [{"price": bid}] if bid else [], "sell": [{"price": ask}] if ask else []}
    return {"symbolToken": token, "ltp": ltp, "depth": depth}


def make_feed(master, quotes):
    feed = AngelOneFeed("k", "c", "p", "s", client=FakeClient(quotes))
    feed._master = master
    return feed


def test_option_tokens_parses_strike_paise_and_rights():
    master = [master_row(25900, "CE", "111"), master_row(25100, "PE", "222"), SPOT_ROW]
    feed = make_feed(master, {})
    tokens = feed.option_tokens("NIFTY", EXPIRY)
    assert tokens[("NIFTY", EXPIRY, 25900.0, Right.CALL)] == "111"
    assert tokens[("NIFTY", EXPIRY, 25100.0, Right.PUT)] == "222"


def test_option_tokens_wrong_expiry_raises():
    feed = make_feed([master_row(25900, "CE", "111", expiry="21JUL2026"), SPOT_ROW], {})
    with pytest.raises(RuntimeError, match="no NIFTY options"):
        feed.option_tokens("NIFTY", EXPIRY)


def test_lot_size_from_master():
    feed = make_feed([master_row(25900, "CE", "111"), SPOT_ROW], {})
    assert feed.lot_size("NIFTY", EXPIRY) == 65


def test_option_chain_quotes_and_spot(monkeypatch):
    monkeypatch.setattr(angelone_mod, "_MIN_CALL_GAP_S", 0)
    master = [master_row(25900, "CE", "111"), master_row(25100, "PE", "222"), SPOT_ROW]
    quotes = {
        "26000": quote_item("26000", 25500.0),
        "111": quote_item("111", 60.0, bid=59.5, ask=60.5),
        "222": quote_item("222", 55.0),
    }
    feed = make_feed(master, quotes)

    assert feed.spot("NIFTY") == 25500.0
    chain = feed.option_chain("NIFTY", EXPIRY)
    call = chain[("NIFTY", EXPIRY, 25900.0, Right.CALL)]
    assert (call.ltp, call.bid, call.ask) == (60.0, 59.5, 60.5)
    put = chain[("NIFTY", EXPIRY, 25100.0, Right.PUT)]
    assert put.ltp == 55.0 and put.bid is None


def test_quote_requests_are_batched(monkeypatch):
    monkeypatch.setattr(angelone_mod, "_MIN_CALL_GAP_S", 0)
    # 60 strikes on one side -> 120 tokens... use 60 total to force 2 batches of <=50.
    master = [SPOT_ROW]
    quotes = {"26000": quote_item("26000", 25500.0)}
    for i in range(60):
        strike = 24000 + i * 50
        token = str(1000 + i)
        master.append(master_row(strike, "CE", token))
        quotes[token] = quote_item(token, 10.0)
    feed = make_feed(master, quotes)
    feed._strikes_around = 100        # keep every strike in range

    feed.option_chain("NIFTY", EXPIRY)
    option_batches = [b for b in feed._client.batches if "26000" not in b]
    assert len(option_batches) == 2
    assert all(len(b) <= 50 for b in option_batches)


def test_pre_fetched_spot_avoids_duplicate_call(monkeypatch):
    monkeypatch.setattr(angelone_mod, "_MIN_CALL_GAP_S", 0)
    master = [master_row(25900, "CE", "111"), SPOT_ROW]
    quotes = {"111": quote_item("111", 60.0)}
    feed = make_feed(master, quotes)
    feed.option_chain("NIFTY", EXPIRY, spot=25500.0)
    assert all("26000" not in b for b in feed._client.batches)  # spot never fetched


def test_zero_and_null_ltp_quotes_are_skipped(monkeypatch):
    monkeypatch.setattr(angelone_mod, "_MIN_CALL_GAP_S", 0)
    master = [master_row(25900, "CE", "111"), master_row(25100, "PE", "222"),
              master_row(25000, "PE", "333"), SPOT_ROW]
    quotes = {
        "111": quote_item("111", 60.0),
        "222": quote_item("222", 0.0),                       # untraded -> skip
        "333": {"symbolToken": "333", "ltp": None, "depth": {}},  # null -> skip, no crash
    }
    feed = make_feed(master, quotes)
    chain = feed.option_chain("NIFTY", EXPIRY, spot=25500.0)
    assert set(chain) == {("NIFTY", EXPIRY, 25900.0, Right.CALL)}


def test_spot_unfetched_raises_clear_error(monkeypatch):
    monkeypatch.setattr(angelone_mod, "_MIN_CALL_GAP_S", 0)
    feed = make_feed([master_row(25900, "CE", "111"), SPOT_ROW], {})  # nothing fetched
    with pytest.raises(RuntimeError, match="no spot quote"):
        feed.spot("NIFTY")


def test_list_expiries_parses_master():
    master = [
        master_row(25900, "CE", "111", expiry="14JUL2026"),
        master_row(25900, "CE", "112", expiry="21JUL2026"),
        SPOT_ROW,
    ]
    feed = make_feed(master, {})
    assert feed.list_expiries("NIFTY") == [date(2026, 7, 14), date(2026, 7, 21)]
