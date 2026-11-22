"""Dollar-accurate simulation of the trend+pullback ETF strategy with a trade journal.

Starts from a real cash amount, buys fractional shares, pays COST on every buy/sell,
and records WHY each trade was opened and closed.

Decisions use closes up to the decision day; fills happen at the NEXT trading day's close.
"""
from dataclasses import dataclass

import pandas as pd

from .etf import COST


@dataclass
class Params:
    name: str
    freq: str          # "W" = decide on Friday closes, "D" = decide every day
    trend_len: int     # SMA length for the trend filter / exit (bars of `freq`)
    mom_len: int       # momentum lookback (bars) -> ~12 months
    ema_len: int       # "area of interest" average to pull back to
    dip_window: int    # pullback must have happened within this many bars
    exit_len: int      # exit when close < SMA(exit_len)
    slots: int = 3
    max_new_per_week: int = 1


WEEKLY = Params("ours weekly", "W", trend_len=40, mom_len=52, ema_len=10, dip_window=3, exit_len=40)
DAILY = Params("ours daily (fast)", "D", trend_len=200, mom_len=252, ema_len=20, dip_window=5, exit_len=50)


def run(px: pd.DataFrame, p: Params, start_cash: float = 100.0, start=None):
    bars = px.resample("W-FRI").last() if p.freq == "W" else px
    if start is not None:
        warm = bars.index[bars.index < pd.Timestamp(start)]
        bars = bars.loc[warm[-max(p.trend_len, p.mom_len) - 5] if len(warm) > p.mom_len else bars.index[0]:]
    sma = bars.rolling(p.trend_len).mean()
    sma_exit = bars.rolling(p.exit_len).mean()
    ema = bars.ewm(span=p.ema_len, adjust=False).mean()
    mom = bars.pct_change(p.mom_len)
    dipped = (bars <= ema).rolling(p.dip_window).max().shift(1).fillna(0).astype(bool)

    cash, pos, trades = start_cash, {}, []   # pos: ticker -> dict(units, entry, date, why)
    pending = []                             # (action, ticker, why) to fill next trading day
    week_new = {}
    days = px.index[px.index >= pd.Timestamp(start)] if start else px.index
    decide_days = set(bars.index)
    equity = []

    for d in days:
        # 1. Fill yesterday's decisions at today's close.
        for action, a, why in pending:
            price = px.at[d, a]
            if action == "sell" and a in pos:
                ps = pos.pop(a)
                cash += ps["units"] * price * (1 - COST)
                pnl = ps["units"] * price * (1 - COST) - ps["cost"]
                trades.append({"ETF": a, "bought": ps["date"].date(), "buy_px": round(ps["entry"], 2),
                               "sold": d.date(), "sell_px": round(price, 2),
                               "days": (d - ps["date"]).days, "pnl_$": round(pnl, 2),
                               "pnl_%": round(pnl / ps["cost"] * 100, 1),
                               "why_in": ps["why"], "why_out": why})
            elif action == "buy" and a not in pos:
                value = sum(v["units"] * px.at[d, k] for k, v in pos.items()) + cash
                spend = min(cash, value / p.slots)
                if spend >= 1.0:  # Alpaca minimum order is $1
                    units = spend * (1 - COST) / price
                    cash -= spend
                    pos[a] = {"units": units, "entry": price, "date": d, "cost": spend, "why": why}
        pending = []

        # 2. Decide at this bar's close (weekly: only on Fridays in `bars`).
        if d in decide_days and d in bars.index:
            t = d
            for a in list(pos):
                if bars.at[t, a] < sma_exit.at[t, a]:
                    pending.append(("sell", a, f"closed {bars.at[t, a]:.2f} below {p.exit_len}-bar avg "
                                              f"{sma_exit.at[t, a]:.2f} -> trend broken"))
            wk = t.to_period("W-FRI")
            open_after = len(pos) - sum(1 for x in pending if x[0] == "sell")
            if open_after < p.slots and week_new.get(wk, 0) < p.max_new_per_week:
                cands = []
                for a in bars.columns:
                    if a in pos:
                        continue
                    c, s, e, m = bars.at[t, a], sma.at[t, a], ema.at[t, a], mom.at[t, a]
                    prev = bars[a].shift(1).at[t]
                    if pd.notna(s) and pd.notna(m) and c > s and m > 0 and dipped.at[t, a] and c > e and c > prev:
                        cands.append((m, a, c, s, e))
                if cands:
                    m, a, c, s, e = max(cands)
                    others = ", ".join(x[1] for x in sorted(cands, reverse=True)[1:]) or "none"
                    why = (f"uptrend ({c:.2f} > {p.trend_len}-bar avg {s:.2f}, 12m {m:+.0%}); "
                           f"dipped to {p.ema_len}-bar avg then closed back above it ({e:.2f}) and up on the bar; "
                           f"strongest trend (also qualified: {others})")
                    pending.append(("buy", a, why))
                    week_new[wk] = week_new.get(wk, 0) + 1

        equity.append(cash + sum(v["units"] * px.at[d, k] for k, v in pos.items()))

    open_now = [{"ETF": k, "bought": v["date"].date(), "buy_px": round(v["entry"], 2),
                 "now_px": round(px.iloc[-1][k], 2),
                 "open_pnl_%": round((px.iloc[-1][k] * (1 - COST) * v["units"] / v["cost"] - 1) * 100, 1),
                 "why_in": v["why"]} for k, v in pos.items()]
    return pd.DataFrame(trades), pd.Series(equity, index=days), open_now
