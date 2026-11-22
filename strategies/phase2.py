"""PHASE 2 RULES -- slow monthly ETF strategies. ONE copy of each rule, used by BOTH the backtest (run_phase2_backtest.py)
and the paper arena (run_phase2.py), so paper trades exactly what was tested.

Every function takes `close` = daily adjusted closes (DataFrame, columns = tickers, rows up to and including the decision
day, NaN before an ETF existed) and returns target weights (pd.Series, sums to 1.0, the leftover sits in BIL = T-bills = cash).
Pre-declared 2026-11-22 in results/sweep_log.csv (P2-A..E). Changing any number here = a NEW strategy name.
"""
import numpy as np
import pandas as pd

CASH = "BIL"
ETF8 = ["SPY", "QQQ", "TLT", "IEF", "GLD", "DBC", "EFA", "VNQ"]
WIDE = ETF8 + ["IWM", "EEM", "EWJ", "LQD", "TIP", "HYG", "SLV", "USO", "DBA", "UNG", "UUP", "FXE", "FXY", "FXB", "FXA", "FXF", "FXC"]
LOOKBACKS = (63, 126, 252)          # ~3, 6, 12 months of trading days
VOLWIN = 63                         # ~3 months
TARGET_VOL = 0.10


def _ok(close, cols, need):
    """tickers with a full `need`-day history ending today (no survivorship: an ETF only joins once it has existed)."""
    tail = close[cols].iloc[-need:]
    return [c for c in cols if len(tail) >= need and tail[c].notna().all()]


def _ret(s, n):
    return s.iloc[-1] / s.iloc[-1 - n] - 1


def _finish(w):
    w = w[w > 1e-6]
    w[CASH] = w.get(CASH, 0.0) + max(0.0, 1.0 - w.drop(CASH, errors="ignore").sum())
    return w


def tsmom(close, universe=ETF8, lookbacks=LOOKBACKS, volwin=VOLWIN, target=TARGET_VOL, signal=None):
    """time-series trend: long an ETF in proportion to how many of its 3/6/12m returns beat cash; size by 1/vol;
    scale the whole book to a 10%/yr volatility, never above 100% invested (no leverage)."""
    need = max(lookbacks) + 1
    elig = _ok(close, universe, need)
    if not elig:
        return pd.Series({CASH: 1.0})
    cash = close[CASH]
    s = pd.Series({a: np.mean([_ret(close[a], n) > _ret(cash, n) for n in lookbacks]) for a in elig})
    if signal is not None:                       # placebo hook: replace the trend signal, keep everything else
        s = signal(s)
    rets = close[elig].iloc[-volwin - 1:].pct_change().iloc[1:]
    vol = rets.std() * np.sqrt(252)
    raw = (s / vol).fillna(0.0)
    if raw.sum() <= 0:
        return pd.Series({CASH: 1.0})
    cov = rets.cov().values * 252
    pv = float(np.sqrt(raw.values @ cov @ raw.values))
    w = raw * (target / pv if pv > 0 else 0)
    if w.sum() > 1.0:
        w = w / w.sum()
    return _finish(w)


def tsmom_wide(close, **kw):
    return tsmom(close, universe=WIDE, **kw)


def dual_momentum(close, lookback=252):
    """Antonacci GEM: if US stocks beat T-bills over 12m, hold the stronger of SPY / EFA; otherwise bonds (AGG)."""
    r = lambda a: _ret(close[a], lookback)
    if r("SPY") > r(CASH):
        return pd.Series({"SPY" if r("SPY") >= r("EFA") else "EFA": 1.0})
    return pd.Series({"AGG": 1.0})


def risk_parity(close, universe=ETF8, volwin=VOLWIN):
    """inverse-volatility weights across the 8 ETFs, always fully invested."""
    elig = _ok(close, universe, volwin + 1)
    vol = close[elig].iloc[-volwin - 1:].pct_change().iloc[1:].std()
    w = (1 / vol) / (1 / vol).sum()
    return _finish(w)


def spy(close):
    return pd.Series({"SPY": 1.0})


def sixty_forty(close):
    return pd.Series({"SPY": 0.6, "AGG": 0.4})


RULES = {"tsmom_etf8": tsmom, "tsmom_wide25": tsmom_wide, "dual_momentum": dual_momentum, "risk_parity8": risk_parity,
         "spy_hold": spy, "sixty_forty": sixty_forty}
UNIVERSE = sorted(set(WIDE + ["AGG", CASH]))
