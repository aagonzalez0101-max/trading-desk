"""Download historical QQQ quotes from Alpaca and keep the last quote of every second.

  python -m bot.quotes iex 2026-10-06 2026-10-07 2026-10-08
  python -m bot.quotes sip 2026-10-06 ...

Regular hours only (9:30-16:00 New York). Saves data/qqq_<feed>_<date>_1s.parquet with
columns bp, ap, bs, as (best bid/ask price and size) indexed by second (UTC).
"""
import os
import sys
import time

import pandas as pd
import requests
from dotenv import load_dotenv

from bot.data import CACHE, ROOT

SYM = "QQQ"


def path(feed, day):
    return CACHE / f"qqq_{feed}_{day}_1s.parquet"


def download_day(feed: str, day: str):
    if path(feed, day).exists():
        return
    load_dotenv(ROOT / ".env")
    h = {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]}
    open_ = pd.Timestamp(f"{day} 09:30", tz="America/New_York").tz_convert("UTC")
    close = pd.Timestamp(f"{day} 16:00", tz="America/New_York").tz_convert("UTC")
    p = {"start": open_.isoformat(), "end": close.isoformat(), "feed": feed, "limit": 10000}
    parts, n = [], 0
    while True:
        for attempt in range(6):
            try:
                j = requests.get(f"https://data.alpaca.markets/v2/stocks/{SYM}/quotes", headers=h, params=p, timeout=60).json()
                break
            except requests.exceptions.RequestException:
                time.sleep(2 ** attempt)
        q = j.get("quotes") or []
        if q:
            df = pd.DataFrame(q)[["t", "bp", "ap", "bs", "as"]]
            df["t"] = pd.to_datetime(df.t, utc=True, format="ISO8601").dt.floor("s")
            parts.append(df.groupby("t").last())
            n += len(q)
        if not j.get("next_page_token"):
            break
        p["page_token"] = j["next_page_token"]
    out = pd.concat(parts)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.to_parquet(path(feed, day))
    print(f"{feed} {day}: {n:,} quotes -> {len(out):,} seconds", flush=True)


if __name__ == "__main__":
    for d in sys.argv[2:]:
        download_day(sys.argv[1], d)
