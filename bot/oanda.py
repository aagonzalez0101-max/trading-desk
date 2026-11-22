"""Minimal OANDA v20 REST client, hard-wired to the PRACTICE (demo) endpoint.

Token comes from .env (OANDA_API_KEY). There is deliberately no way to point this at
the live endpoint.

  python -m bot.oanda download EUR_USD GBP_USD USD_JPY   # 1-minute bid/ask candles since 2023
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

PRACTICE_URL = "https://api-fxpractice.oanda.com"
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data"
M1_START = "2023-01-01T00:00:00Z"


class Practice:
    def __init__(self):
        load_dotenv(ROOT / ".env")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {os.environ['OANDA_API_KEY']}",
                               "Accept-Datetime-Format": "RFC3339"})
        self.account_id = self._req("GET", "/v3/accounts")["accounts"][0]["id"]

    def _req(self, method, path, **kw):
        for attempt in range(5):
            r = self.s.request(method, PRACTICE_URL + path, timeout=60, **kw)
            if r.status_code == 429 or r.status_code >= 500:  # rate limit / server hiccup
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"OANDA {method} {path} -> {r.status_code}: {r.text}")
            return r.json()
        raise RuntimeError(f"OANDA {method} {path} kept failing ({r.status_code})")

    def summary(self):
        return self._req("GET", f"/v3/accounts/{self.account_id}/summary")["account"]

    def candles(self, pair, granularity, start=None, count=5000):
        p = {"granularity": granularity, "price": "BA", "count": count}
        if start:
            p["from"] = start
        return self._req("GET", f"/v3/instruments/{pair}/candles", params=p)["candles"]

    def price(self, pair):
        p = self._req("GET", f"/v3/accounts/{self.account_id}/pricing", params={"instruments": pair})["prices"][0]
        return float(p["bids"][0]["price"]), float(p["asks"][0]["price"]), p["tradeable"]

    def market_order(self, pair, units: int, stop: float, target: float, decimals: int = 5):
        """Market order (fill-or-kill) with stop-loss and take-profit attached. units > 0 buys, < 0 sells."""
        order = {"type": "MARKET", "instrument": pair, "units": str(units), "timeInForce": "FOK",
                 "positionFill": "DEFAULT", "stopLossOnFill": {"price": f"{stop:.{decimals}f}"},
                 "takeProfitOnFill": {"price": f"{target:.{decimals}f}"}}
        return self._req("POST", f"/v3/accounts/{self.account_id}/orders", json={"order": order})

    def trade(self, trade_id):
        return self._req("GET", f"/v3/accounts/{self.account_id}/trades/{trade_id}")["trade"]

    def close_trade(self, trade_id):
        return self._req("PUT", f"/v3/accounts/{self.account_id}/trades/{trade_id}/close")

    def open_trades(self):
        return self._req("GET", f"/v3/accounts/{self.account_id}/openTrades")["trades"]


def m1_path(pair: str) -> Path:
    return CACHE / f"{pair}_M1_BA.parquet"


def download_m1(api: Practice, pair: str):
    """Fetch complete 1-minute bid/ask candles from M1_START to now; resumes where it left off."""
    path = m1_path(pair)
    old = pd.read_parquet(path) if path.exists() else None
    start = (old.index[-1] + pd.Timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ") if old is not None else M1_START
    rows, n = [], 0
    while True:
        cs = api.candles(pair, "M1", start)
        done = [c for c in cs if c["complete"]]
        rows += [(c["time"], *(float(c[s][k]) for s in ("bid", "ask") for k in "ohlc"), c["volume"]) for c in done]
        n += 1
        if len(cs) < 5000 or not done:
            break
        start = done[-1]["time"]
        rows.pop()  # 'from' is inclusive; the next page re-sends this candle
        if n % 50 == 0:
            print(f"  {pair}: {len(rows):,} new candles, up to {start[:10]}", flush=True)
    cols = ["bo", "bh", "bl", "bc", "ao", "ah", "al", "ac", "volume"]
    new = pd.DataFrame(rows, columns=["time", *cols]).set_index("time")
    new.index = pd.to_datetime(new.index, utc=True)
    df = pd.concat([old, new]) if old is not None else new
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.to_parquet(path)
    print(f"{pair}: {len(df):,} candles, {df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d %H:%M} UTC")


if __name__ == "__main__":
    if sys.argv[1:2] == ["download"]:
        api = Practice()
        for pair in sys.argv[2:]:
            download_m1(api, pair)
