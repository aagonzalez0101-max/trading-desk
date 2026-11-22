"""Minimal Alpaca REST client, hard-wired to the PAPER endpoint.

Keys come from .env (ALPACA_API_KEY / ALPACA_SECRET_KEY). There is deliberately no
way to point this at the live endpoint.
"""
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

PAPER_URL = "https://paper-api.alpaca.markets"
ROOT = Path(__file__).resolve().parent.parent


# which .env names hold which paper account's keys (user 11/22: only the $500 and $10k accounts exist now)
ACCOUNTS = {"old": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"), "500": ("ALPACA_KEY_500", "ALPACA_SECRET_500"),
            "10k": ("ALPACA_KEY_10K", "ALPACA_SECRET_10K")}


def have_keys(acct: str = "old") -> bool:
    load_dotenv(ROOT / ".env")
    k, s = ACCOUNTS[acct]
    return bool(os.getenv(k) and os.getenv(s))


class Paper:
    def __init__(self, acct: str = "old"):
        load_dotenv(ROOT / ".env")
        k, s = ACCOUNTS[acct]
        self.acct = acct
        self.s = requests.Session()
        self.s.headers.update({"APCA-API-KEY-ID": os.environ[k], "APCA-API-SECRET-KEY": os.environ[s]})

    def _req(self, method, path, **kw):
        # reads retry on a dropped connection; orders (POST) never retry -- a retry could place the same order twice
        for i in range(4 if method == "GET" else 1):
            try:
                r = self.s.request(method, PAPER_URL + path, timeout=30, **kw)
                break
            except requests.exceptions.ConnectionError:
                if method != "GET" or i == 3:
                    raise
                time.sleep(3 * (i + 1))
        if r.status_code >= 400:
            raise RuntimeError(f"Alpaca {method} {path} -> {r.status_code}: {r.text}")
        return r.json() if r.text else None

    def account(self):
        return self._req("GET", "/v2/account")

    def clock(self):
        return self._req("GET", "/v2/clock")

    def positions(self) -> dict:
        return {p["symbol"]: p for p in self._req("GET", "/v2/positions")}

    def open_orders(self):
        return self._req("GET", "/v2/orders", params={"status": "open"})

    def asset(self, symbol):
        return self._req("GET", f"/v2/assets/{symbol}")

    def close_position(self, symbol):
        return self._req("DELETE", f"/v2/positions/{symbol}")

    def buy(self, symbol, notional=None, qty=None):
        order = {"symbol": symbol, "side": "buy", "type": "market", "time_in_force": "day"}
        if notional is not None:
            order["notional"] = f"{notional:.2f}"
        else:
            order["qty"] = str(qty)
        return self._req("POST", "/v2/orders", json=order)

    def order(self, order_id):
        return self._req("GET", f"/v2/orders/{order_id}")

    def calendar(self, start, end):
        return self._req("GET", "/v2/calendar", params={"start": str(start), "end": str(end)})

    def daily_bars(self, symbols, start, end):
        """free SIP daily bars (needs end >= 15 min old), split/dividend adjusted -> {symbol: [(date, close, open)]}"""
        out, token = {}, None
        while True:
            p = dict(symbols=",".join(symbols), timeframe="1Day", start=str(start), end=str(end), adjustment="all",
                     feed="sip", limit=10000)
            if token:
                p["page_token"] = token
            for i in range(4):
                try:
                    r = self.s.get("https://data.alpaca.markets/v2/stocks/bars", params=p, timeout=60)
                    break
                except requests.exceptions.ConnectionError:
                    if i == 3:
                        raise
                    time.sleep(3 * (i + 1))
            if r.status_code >= 400:
                raise RuntimeError(f"Alpaca bars -> {r.status_code}: {r.text[:200]}")
            j = r.json()
            for sym, bars in (j.get("bars") or {}).items():
                out.setdefault(sym, []).extend((b["t"][:10], b["c"], b["o"]) for b in bars)
            token = j.get("next_page_token")
            if not token:
                return out

    def sell(self, symbol, qty):
        order = {"symbol": symbol, "side": "sell", "type": "market", "time_in_force": "day", "qty": str(qty)}
        return self._req("POST", "/v2/orders", json=order)

    def wait_filled(self, order_id, timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            o = self._req("GET", f"/v2/orders/{order_id}")
            if o["status"] in ("filled", "canceled", "expired", "rejected"):
                return o
            time.sleep(2)
        return o
