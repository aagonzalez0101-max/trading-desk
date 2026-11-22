"""Historical price data: download hourly bid candles from Dukascopy and cache them.

Higher timeframes (4H, daily, weekly) are built from the hourly candles so every
timeframe lines up exactly. Forex days roll over at 22:00 UTC (5pm New York).
"""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data"
CACHE.mkdir(exist_ok=True)
OUT = ROOT / "results"
OUT.mkdir(exist_ok=True)

# Typical OANDA spreads in pips (assumed; real spreads widen at news/rollover, and the
# 2023+ 1-minute data showed EUR/USD ~1.6, GBP/USD ~1.9, USD/JPY ~1.7 median).
SPREAD_PIPS = {
    "EUR_USD": 1.4, "GBP_USD": 2.0, "USD_JPY": 1.4, "AUD_USD": 1.4, "USD_CAD": 2.2,
    "NZD_USD": 2.0, "USD_CHF": 1.8, "EUR_JPY": 2.0, "GBP_JPY": 3.0, "EUR_AUD": 2.5,
    "GBP_CAD": 3.5, "GBP_NZD": 4.5, "AUD_JPY": 2.0,
}

PAIRS = [
    "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD", "NZD_USD", "USD_CHF",
    "EUR_JPY", "GBP_JPY", "EUR_AUD", "GBP_CAD", "GBP_NZD", "AUD_JPY",
]
START = datetime(2015, 1, 1, tzinfo=timezone.utc)


def pip_size(pair: str) -> float:
    return 0.01 if pair.endswith("JPY") else 0.0001


def _instrument(pair: str):
    import dukascopy_python.instruments as inst
    for group in ("MAJORS", "CROSSES"):
        name = f"INSTRUMENT_FX_{group}_{pair}"
        if hasattr(inst, name):
            return getattr(inst, name)
    raise ValueError(f"unknown pair {pair}")


def download(pair: str, start: datetime = START, end: datetime | None = None) -> pd.DataFrame:
    """Download hourly bid candles one year at a time and cache to CSV."""
    import dukascopy_python as dp

    end = end or datetime.now(timezone.utc)
    path = CACHE / f"{pair}_H1.csv"
    frames = []
    if path.exists():
        old = load_hourly(pair)
        frames.append(old)
        start = old.index[-1].to_pydatetime()
    year_start = start
    while year_start < end:
        year_end = min(datetime(year_start.year + 1, 1, 1, tzinfo=timezone.utc), end)
        df = dp.fetch(_instrument(pair), dp.INTERVAL_HOUR_1, dp.OFFER_SIDE_BID, year_start, year_end)
        if len(df):
            frames.append(df[["open", "high", "low", "close"]])
        print(f"{pair} {year_start:%Y-%m-%d} -> {year_end:%Y-%m-%d}: {len(df)} bars", flush=True)
        year_start = year_end
    out = pd.concat(frames)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.to_csv(path)
    return out


def load_hourly(pair: str) -> pd.DataFrame:
    df = pd.read_csv(CACHE / f"{pair}_H1.csv", index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    # Drop flat weekend placeholder bars.
    return df[(df.high > df.low) | (df.index.dayofweek < 5)]


def resample(h1: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Build higher-timeframe candles. Index = bar OPEN time; 'close_time' = when it's final."""
    # Forex days roll at 5pm New York (21:00 or 22:00 UTC depending on DST). Shift NY
    # time +7h so the rollover lands on midnight, then bucket on that clock.
    ny = h1.index.tz_convert("America/New_York").tz_localize(None) + pd.Timedelta(hours=7)
    day = ny.normalize()
    if rule == "W":
        key = day - pd.to_timedelta(day.dayofweek, unit="D")  # week opens Sunday 5pm NY
    elif rule == "D":
        key = day
    else:
        key = ny.floor(rule)
    g = h1.assign(t=h1.index).groupby(key.to_numpy())
    out = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                close=("close", "last"), t0=("t", "first"), t1=("t", "last"))
    # A candle is final once its last hourly bar has closed.
    out = out.set_index("t0").rename_axis(None)
    out["close_time"] = out.pop("t1") + pd.Timedelta(hours=1)
    return out


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:] or PAIRS:
        download(p)
