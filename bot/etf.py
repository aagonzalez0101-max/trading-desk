"""Long-only multi-asset trend following on ETFs (daily data from Yahoo).

Each ETF gets an equal slice of the account. A slice is invested while that ETF is
trending up, otherwise it sits in cash. Buy-only because a $10 account can't short.

Rules are decided on a close and traded at the NEXT day's close (no lookahead).
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data"

# US stocks, intl stocks, emerging, long bonds, mid bonds, gold, commodities, real estate
ETFS = ["SPY", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ"]
COST = 0.0005  # 0.05% per unit of turnover (spread; Alpaca charges no commission)


def load(tickers=ETFS) -> pd.DataFrame:
    path = CACHE / "etf_daily.csv"
    if path.exists():
        px = pd.read_csv(path, index_col=0, parse_dates=True)
        if set(tickers) <= set(px.columns):
            return px[tickers]
    import yfinance as yf
    raw = yf.download(tickers, start="2000-01-01", auto_adjust=True, progress=False)
    px = raw["Close"][tickers].dropna()  # adjusted for dividends/splits
    px.to_csv(path)
    return px


def faber_10m(px: pd.DataFrame) -> pd.DataFrame:
    """Invested if month-end close > 10-month average of month-end closes. Checked monthly."""
    m = px.resample("ME").last()
    sig = (m > m.rolling(10).mean()).astype(float)
    sig = sig.reindex(px.index, method="ffill")
    # Month-end decision takes effect from the next trading day.
    return sig.shift(1)


def ema_16_64(px: pd.DataFrame) -> pd.DataFrame:
    """Invested while daily EMA16 > EMA64. Checked every day."""
    sig = (px.ewm(span=16, adjust=False).mean() > px.ewm(span=64, adjust=False).mean()).astype(float)
    return sig.shift(1)


def _weekly_to_daily(sig_w: pd.DataFrame, px: pd.DataFrame) -> pd.DataFrame:
    # Friday-close decision takes effect from the next trading day.
    return sig_w.reindex(px.index, method="ffill").shift(1)


def faber_weekly(px: pd.DataFrame) -> pd.DataFrame:
    """Faber rule checked every Friday: invested if close > 40-week average (~10 months)."""
    w = px.resample("W-FRI").last()
    return _weekly_to_daily((w > w.rolling(40).mean()).astype(float), px)


def rotation(lookback_weeks: int):
    """Each Friday hold the ONE ETF with the best return over `lookback_weeks`, if it's
    also above its 40-week average; otherwise cash. At most one switch per week."""
    def strat(px: pd.DataFrame) -> pd.DataFrame:
        w = px.resample("W-FRI").last()
        mom = w.pct_change(lookback_weeks)
        up = w > w.rolling(40).mean()
        eligible = mom.where(up)
        hold = pd.DataFrame(0.0, index=w.index, columns=w.columns)
        for t, row in eligible.iterrows():
            if row.notna().any():  # otherwise nothing is trending up -> cash
                hold.loc[t, row.idxmax()] = float(len(w.columns))  # whole account
        return _weekly_to_daily(hold, px)
    return strat


def trend_pullback(px: pd.DataFrame, slots: int = 3) -> pd.DataFrame:
    """Our own weekly strategy: research trend filter + AlexG-style patience.

    Checked every Friday close:
      trend    : close > 40-week SMA and 12-month return > 0        (research)
      pullback : some close in the last 3 weeks was at/below 10-week EMA  (don't chase highs)
      confirm  : this close is back above the 10-week EMA and above last week's close
      entry    : at most ONE new position per week, strongest 12-month trend first
      exit     : weekly close below the 40-week SMA (trend broken); otherwise hold
      sizing   : up to `slots` positions, 1/slots of the account each
    """
    w = px.resample("W-FRI").last()
    sma40 = w.rolling(40).mean()
    ema10 = w.ewm(span=10, adjust=False).mean()
    mom12 = w.pct_change(52)
    trend = (w > sma40) & (mom12 > 0)
    dipped = (w <= ema10).rolling(3).max().astype(bool)
    confirm = (w > ema10) & (w > w.shift(1))
    entry_ok = trend & dipped.shift(1, fill_value=False) & confirm

    held: set = set()
    hold = pd.DataFrame(0.0, index=w.index, columns=w.columns)
    for t in w.index:
        held = {a for a in held if w.at[t, a] >= sma40.at[t, a]}  # exits first
        if len(held) < slots:
            cands = [a for a in w.columns if a not in held and entry_ok.at[t, a]]
            if cands:
                held.add(max(cands, key=lambda a: mom12.at[t, a]))  # one new trade per week
        for a in held:
            hold.at[t, a] = len(w.columns) / slots  # simulate() divides by N columns
    return _weekly_to_daily(hold, px)


def buy_hold(px: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(1.0, index=px.index, columns=px.columns)


def simulate(px: pd.DataFrame, signal: pd.DataFrame) -> pd.Series:
    """Daily portfolio returns. Equal-weight slices, cash earns 0 (conservative)."""
    rets = px.pct_change()
    w = signal / len(px.columns)
    gross = (w * rets).sum(axis=1)
    turnover = w.diff().abs().sum(axis=1)
    return (gross - turnover * COST).dropna()


def summarize(r: pd.Series) -> dict:
    eq = (1 + r).cumprod()
    years = len(r) / 252
    return {
        "cagr": eq.iloc[-1] ** (1 / years) - 1,
        "vol": r.std() * np.sqrt(252),
        "sharpe": r.mean() / r.std() * np.sqrt(252),
        "max_dd": (eq / eq.cummax() - 1).min(),
        "worst_year": r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1).min(),
    }
