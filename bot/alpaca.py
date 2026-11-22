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


def have_keys() -> bool:
    load_dotenv(ROOT / ".env")
    return bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"))


class Paper:
    def __init__(self):
        load_dotenv(ROOT / ".env")
        self.s = requests.Session()
        self.s.headers.update({
            "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
        })

    def _req(self, method, path, **kw):
        r = self.s.request(method, PAPER_URL + path, timeout=30, **kw)
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
