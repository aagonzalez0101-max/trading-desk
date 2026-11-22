"""Pre-declared day-trading test: SPY intraday momentum (Gao, Han, Li & Zhou 2018,
"Market Intraday Momentum", Journal of Financial Economics).

Written down BEFORE running (2026-10-08). Exactly two variants, no tuning:
  signal : SPY's return from yesterday's 4:00pm close to today's 10:00am (first half hour)
  trade  : at 3:30pm, bet that direction; exit at the 4:00pm close. Flat overnight.
  A. both : up bet if the first half hour was up, down bet if it was down
  B. long : up bet only when the first half hour was up (works in a cash account)
Sizing: whole account, no leverage. Costs: 0.02% of the trade per round trip
(SPY's 1-cent spread plus slippage; generous). Half-days (no 3:30 bar) are skipped.
PASS = profitable after costs in BOTH 2016-2021 and 2022-now, worst drop better than -25%.
Benchmark (not a variant): always buy at 3:30 and sell at 4:00.

Data: Alpaca 30-minute SIP bars, split/dividend adjusted, cached to data/SPY_30m.csv.
"""
import os
from datetime import datetime

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

from bot.alpaca import ROOT
from bot.data import OUT

CSV = ROOT / "data" / "SPY_30m.csv"
COST = 0.0002
SPLIT = "2022-01-01"


def bars() -> pd.DataFrame:
    if CSV.exists():
        df = pd.read_csv(CSV, index_col=0)
        df.index = pd.to_datetime(df.index, utc=True)
        return df
    load_dotenv(ROOT / ".env")
    h = {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]}
    params = {"timeframe": "30Min", "start": "2016-01-01T00:00:00Z", "feed": "sip",
              "adjustment": "all", "limit": 10000}
    rows = []
    while True:
        j = requests.get("https://data.alpaca.markets/v2/stocks/SPY/bars", headers=h, params=params, timeout=60).json()
        rows += j["bars"]
        if not j.get("next_page_token"):
            break
        params["page_token"] = j["next_page_token"]
    df = pd.DataFrame(rows).rename(columns={"t": "time", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df.set_index(pd.to_datetime(df.time, utc=True))[["open", "high", "low", "close", "volume"]]
    df.to_csv(CSV)
    return df


def daily_table(df: pd.DataFrame) -> pd.DataFrame:
    ny = df.copy()
    ny.index = ny.index.tz_convert("America/New_York")
    ny["date"], ny["slot"] = ny.index.date, ny.index.strftime("%H:%M")
    piv = lambda col, slot: ny[ny.slot == slot].set_index("date")[col]
    t = pd.DataFrame({"first_close": piv("close", "09:30"),   # 9:30-10:00 bar close = 10:00 price
                      "last_open": piv("open", "15:30"),      # 3:30pm price
                      "last_close": piv("close", "15:30")})   # 4:00pm close
    t.index = pd.to_datetime(t.index)
    t["prev_close"] = t.last_close.shift(1)
    t = t.dropna()  # drops half-days and the first day
    t["first_ret"] = t.first_close / t.prev_close - 1
    t["last_ret"] = t.last_close / t.last_open - 1
    return t


def run(t: pd.DataFrame, variant: str) -> pd.Series:
    side = np.sign(t.first_ret)
    if variant == "long":
        side = side.clip(lower=0)
    elif variant == "always":
        side = pd.Series(1.0, index=t.index)
    return side * t.last_ret - side.abs() * COST


def stats(r: pd.Series) -> dict:
    eq = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    traded = r[r != 0]
    return {"$100_becomes": 100 * eq.iloc[-1], "per_yr": eq.iloc[-1] ** (1 / yrs) - 1,
            "worst_drop": (eq / eq.cummax() - 1).min(), "trades": len(traded),
            "win_rate": (traded > 0).mean(), "avg_trade_$per100": 100 * traded.mean()}


if __name__ == "__main__":
    t = daily_table(bars())
    print(f"{len(t)} full trading days, {t.index[0]:%Y-%m-%d} to {t.index[-1]:%Y-%m-%d}")
    rows = []
    for variant in ("both", "long", "always"):
        r = run(t, variant)
        for label, part in (("2016-2021", r[r.index < SPLIT]), ("2022-now", r[r.index >= SPLIT])):
            rows.append({"variant": variant, "period": label, **stats(part)})
    df = pd.DataFrame(rows)
    verdict = {v: bool(((g.per_yr > 0) & (g.worst_drop > -0.25)).all()) for v, g in df.groupby("variant") if v != "always"}
    df["PASS"] = df.variant.map(verdict).map({True: "PASS", False: "FAIL"}).fillna("benchmark")
    df.to_csv(OUT / "intraday_momentum.csv", index=False)
    log = OUT / "sweep_log.csv"
    pd.DataFrame([{"time": datetime.now().isoformat(timespec="seconds"), "variant": f"spy_intraday_{r['variant']} [{r['period']}]",
                   "pairs": 1, "trades": r["trades"], "win_rate": r["win_rate"],
                   "total_return": r["$100_becomes"] / 100 - 1, "cagr": r["per_yr"], "max_drawdown": r["worst_drop"]}
                  for r in rows if r["variant"] != "always"]
                 ).reindex(columns=pd.read_csv(log, nrows=0).columns).to_csv(log, mode="a", header=False, index=False)
    pd.set_option("display.width", 200)
    print(df.to_string(index=False, formatters={"$100_becomes": "${:,.2f}".format, "per_yr": "{:+.1%}".format,
                                                "worst_drop": "{:.1%}".format, "win_rate": "{:.0%}".format,
                                                "avg_trade_$per100": "{:+.3f}".format}))
    # Robustness: does the first-half-hour move actually predict the last half hour?
    for label, part in (("2016-2021", t[t.index < SPLIT]), ("2022-now", t[t.index >= SPLIT])):
        print(f"{label}: correlation first-half-hour vs last-half-hour = {part.first_ret.corr(part.last_ret):+.3f}")
