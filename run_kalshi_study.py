"""Would "buy both sides at 49 cents" have made money on Kalshi's 15-minute Bitcoin markets?

  python run_kalshi_study.py --days 14     # download trade history for settled markets (resumes)
  python run_kalshi_study.py --report      # simulate the $5 account

Read-only: uses Kalshi's public market data, no account, no orders.

On Kalshi a NO bid is the same as a YES offer, so buying both sides instantly always costs
>= $1.00. The only way to own both for 98 cents is to POST bids and wait to be filled.
Simulation (fixed before running): at each market's open, post a bid at price P on YES and
on NO, 5 contracts each ($5 account). A bid counts as filled only if the trade history shows
someone sold THROUGH it (a trade printed at a worse price for the seller), so we never assume
we were first in the queue ("conservative"). The "optimistic" column also counts trades
exactly AT our price.
  both filled -> 5 x ($1 - 2P) minus fees     one filled -> held to the result: +5 x (1-P) or -5 x P
Maker fee assumption: 0.0175 x contracts x P x (1-P), rounded up to the cent, per order
(Kalshi's maker rate where it applies); the no-fee case is shown too.
"""
import argparse
import math
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

from bot.data import CACHE, OUT

BASE = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = "KXBTC15M"
SUMMARY = CACHE / "kalshi_btc15m_markets.csv"
CONTRACTS = 5


def get(path, **params):
    for attempt in range(6):
        try:
            r = requests.get(BASE + path, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(1 + attempt)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Kalshi {path} kept failing")


def settled_markets(days):
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    out, cursor = [], None
    while True:
        p = {"series_ticker": SERIES, "status": "settled", "limit": 1000, "min_close_ts": since}
        if cursor:
            p["cursor"] = cursor
        j = get("/markets", **p)
        out += j.get("markets", [])
        cursor = j.get("cursor")
        if not cursor or not j.get("markets"):
            return out


def summarize(m):
    """Lowest and highest YES trade price over the market's life, from 1-minute candles.

    While our YES bid rests at P, any trade printing below P means our bid was filled first
    (either a seller hit bids down through P, or an offer below P would have matched us).
    Same for our NO bid with YES prices above 1 - P."""
    s = int(pd.Timestamp(m["open_time"]).timestamp())
    e = int(pd.Timestamp(m["close_time"]).timestamp())
    cs = get(f"/series/{SERIES}/markets/{m['ticker']}/candlesticks", start_ts=s, end_ts=e,
             period_interval=1).get("candlesticks", [])
    lows = [float(c["price"]["low_dollars"]) for c in cs if c.get("price", {}).get("low_dollars")]
    highs = [float(c["price"]["high_dollars"]) for c in cs if c.get("price", {}).get("high_dollars")]
    vol = sum(float(c.get("volume_fp") or 0) for c in cs)
    return {"minutes": len(cs), "volume": vol,
            "min_yes_fill": min(lows) if lows else np.nan,
            "min_no_fill": 1 - max(highs) if highs else np.nan}


def download(days):
    done = pd.read_csv(SUMMARY) if SUMMARY.exists() else pd.DataFrame(columns=["ticker"])
    have = set(done.ticker)
    ms = [m for m in settled_markets(days) if m["ticker"] not in have and m.get("result") in ("yes", "no")]
    print(f"{len(ms)} new settled markets to fetch ({len(have)} cached)", flush=True)
    rows = []
    for i, m in enumerate(ms, 1):
        rows.append({"ticker": m["ticker"], "close_time": m["close_time"], "result": m["result"], **summarize(m)})
        if i % 50 == 0 or i == len(ms):
            pd.concat([done, pd.DataFrame(rows)]).to_csv(SUMMARY, index=False)
            print(f"  {i}/{len(ms)} fetched", flush=True)


MINUTES = CACHE / "kalshi_btc15m_minutes.parquet"


def download_minutes():
    """Per-minute candles (trade low/high, YES bid/ask close) for every market in the summary."""
    df = pd.read_csv(SUMMARY)
    old = pd.read_parquet(MINUTES) if MINUTES.exists() else pd.DataFrame(columns=["ticker"])
    todo = df[~df.ticker.isin(set(old.ticker))]
    rows = []
    f = lambda c, k, sub: float(c[k][sub]) if c.get(k) and c[k].get(sub) not in (None, "") else np.nan
    for i, m in enumerate(todo.itertuples(), 1):
        close = pd.Timestamp(m.close_time)
        s, e = int((close - pd.Timedelta(minutes=15)).timestamp()), int(close.timestamp())
        cs = get(f"/series/{SERIES}/markets/{m.ticker}/candlesticks", start_ts=s, end_ts=e, period_interval=1).get("candlesticks", [])
        for k, c in enumerate(cs):
            rows.append({"ticker": m.ticker, "minute": k, "low": f(c, "price", "low_dollars"), "high": f(c, "price", "high_dollars"),
                         "bid": f(c, "yes_bid", "close_dollars"), "ask": f(c, "yes_ask", "close_dollars")})
        if i % 100 == 0:
            print(f"  minutes: {i}/{len(todo)}", flush=True)
    pd.concat([old, pd.DataFrame(rows)]).to_parquet(MINUTES)


def taker_fee(price, contracts=CONTRACTS):
    return math.ceil(0.07 * contracts * price * (1 - price) * 100 - 1e-9) / 100


def simulate_exit(df, price, wait, with_fee):
    """Post both bids at open. When one side fills, give the other `wait` minutes to fill too;
    if it doesn't, cancel it and SELL the filled side at that minute's closing bid (paying the
    taker fee). If the market ends first, hold to the result."""
    mins = pd.read_parquet(MINUTES)
    res = df.set_index("ticker").result
    c, mf = CONTRACTS, (fee(price) if with_fee else 0.0)
    out = []
    for tkr, g in mins.groupby("ticker"):
        g = g.sort_values("minute")
        lo, hi, bid, ask = (g[k].to_numpy() for k in ("low", "high", "bid", "ask"))
        fy = next((k for k in range(len(g)) if lo[k] < price - 1e-9), None)
        fn = next((k for k in range(len(g)) if hi[k] > 1 - price + 1e-9), None)
        if fy is None and fn is None:
            out.append((tkr, "none", 0.0))
            continue
        first = min(k for k in (fy, fn) if k is not None)
        second = max(fy, fn) if fy is not None and fn is not None else None
        if second is not None and second <= first + wait:
            out.append((tkr, "both", c * (1 - 2 * price) - 2 * mf))
            continue
        side = "yes" if fy == first else "no"
        k = first + wait
        sell = (bid[k] if side == "yes" else 1 - ask[k]) if k < len(g) else np.nan
        if np.isnan(sell) or sell <= 0:                     # market over or no bid: hold to result
            pnl = (c * (1 - price) if res[tkr] == side else -c * price) - mf
            out.append((tkr, "held", pnl))
        else:
            out.append((tkr, "dumped", c * (sell - price) - mf - (taker_fee(sell) if with_fee else 0.0)))
    return pd.DataFrame(out, columns=["ticker", "outcome", "pnl"])


def report_exit():
    df = pd.read_csv(SUMMARY)
    days = (pd.to_datetime(df.close_time).max() - pd.to_datetime(df.close_time).min()).total_seconds() / 86400
    rows = []
    for price in (0.49, 0.48, 0.45):
        for wait in (0, 1, 2):
            for with_fee in (True, False):
                s = simulate_exit(df, price, wait, with_fee)
                eq = 5 + s.pnl.cumsum()
                vc = s.outcome.value_counts(normalize=True)
                rows.append({"bid": f"{price:.2f}", "wait_min": wait, "fees": "yes" if with_fee else "no",
                             "both": vc.get("both", 0), "dumped": vc.get("dumped", 0), "held": vc.get("held", 0),
                             "avg_dump_$": s[s.outcome == "dumped"].pnl.mean(), "avg_per_market_$": s.pnl.mean(),
                             "per_day_$": s.pnl.sum() / days, "lowest_balance_$": eq.min(),
                             "t_stat": s.pnl.mean() / s.pnl.std() * np.sqrt(len(s)) if s.pnl.std() > 0 else np.nan})
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "kalshi_study_exit.csv", index=False)
    pd.set_option("display.width", 220)
    print(res.to_string(index=False, formatters={"both": "{:.0%}".format, "dumped": "{:.0%}".format, "held": "{:.0%}".format,
          "avg_dump_$": "{:+.2f}".format, "avg_per_market_$": "{:+.3f}".format, "per_day_$": "{:+.2f}".format,
          "lowest_balance_$": "{:.2f}".format, "t_stat": "{:+.2f}".format}))


def fee(price, contracts=CONTRACTS):
    return math.ceil(0.0175 * contracts * price * (1 - price) * 100 - 1e-9) / 100


def simulate(df, price, optimistic, with_fee):
    hit = (lambda m: m <= price + 1e-9) if optimistic else (lambda m: m < price - 1e-9)
    yes_f, no_f = df.min_yes_fill.map(hit).fillna(False), df.min_no_fill.map(hit).fillna(False)
    c, f = CONTRACTS, (fee(price) if with_fee else 0.0)
    pnl = np.where(yes_f & no_f, c * (1 - 2 * price) - 2 * f,
          np.where(yes_f, np.where(df.result == "yes", c * (1 - price), -c * price) - f,
          np.where(no_f, np.where(df.result == "no", c * (1 - price), -c * price) - f, 0.0)))
    return pd.DataFrame({"both": yes_f & no_f, "one": yes_f ^ no_f, "pnl": pnl}, index=df.index)


def report():
    df = pd.read_csv(SUMMARY).sort_values("close_time").reset_index(drop=True)
    days = (pd.to_datetime(df.close_time.iloc[-1]) - pd.to_datetime(df.close_time.iloc[0])).total_seconds() / 86400
    print(f"{len(df)} settled 15-minute BTC markets over {days:.1f} days; median {df.volume.median():,.0f} contracts traded per market\n")
    rows = []
    for price in (0.49, 0.48, 0.45):
        for opt in (False, True):
            for with_fee in (True, False):
                s = simulate(df, price, opt, with_fee)
                eq = 5 + s.pnl.cumsum()
                rows.append({"bid": f"{price:.2f}", "fills": "optimistic" if opt else "conservative",
                             "fees": "yes" if with_fee else "no", "both_filled": s.both.mean(), "one_side_only": s.one.mean(),
                             "avg_per_market_$": s.pnl.mean(), "total_$": s.pnl.sum(), "per_day_$": s.pnl.sum() / days,
                             "worst_market_$": s.pnl.min(), "lowest_balance_$": eq.min(),
                             "t_stat": s.pnl.mean() / s.pnl.std() * np.sqrt(len(s)) if s.pnl.std() > 0 else np.nan})
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "kalshi_study.csv", index=False)
    pd.set_option("display.width", 220)
    print(res.to_string(index=False, formatters={"both_filled": "{:.0%}".format, "one_side_only": "{:.0%}".format,
          "avg_per_market_$": "{:+.3f}".format, "total_$": "{:+.2f}".format, "per_day_$": "{:+.2f}".format,
          "worst_market_$": "{:+.2f}".format, "lowest_balance_$": "{:.2f}".format, "t_stat": "{:+.2f}".format}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--exit", action="store_true", help="simulate dumping the filled leg when the other side doesn't follow")
    a = ap.parse_args()
    if a.days:
        download(a.days)
    if a.exit:
        download_minutes()
        report_exit()
    elif a.report or not a.days:
        report()
