"""One week's decision for the trend+pullback ETF strategy, for live/paper trading.

Same rules as journal.run() with WEEKLY params, but as a pure function of
(daily closes up to a Friday, ETFs currently held) so the live bot and a
historical replay can both call it.
"""
from dataclasses import dataclass, field

import pandas as pd

from .journal import WEEKLY, Params


@dataclass
class Decision:
    week: pd.Timestamp                 # the Friday whose close was used
    sells: dict = field(default_factory=dict)   # ticker -> why
    buy: str | None = None
    buy_why: str = ""


def weekly_bars(px: pd.DataFrame, friday: pd.Timestamp) -> pd.DataFrame:
    """Weekly closes up to and including the week ending `friday` (holiday Fridays use Thursday)."""
    w = px[px.index <= friday].resample("W-FRI").last()
    return w[w.index <= friday]


def decide(px: pd.DataFrame, held: set, friday: pd.Timestamp, p: Params = WEEKLY) -> Decision:
    bars = weekly_bars(px, friday)
    t = bars.index[-1]
    sma = bars.rolling(p.trend_len).mean()
    sma_exit = bars.rolling(p.exit_len).mean()
    ema = bars.ewm(span=p.ema_len, adjust=False).mean()
    mom = bars.pct_change(p.mom_len)
    dipped = (bars <= ema).rolling(p.dip_window).max().shift(1).fillna(0).astype(bool)

    d = Decision(week=t)
    for a in sorted(held):
        if a in bars.columns and bars.at[t, a] < sma_exit.at[t, a]:
            d.sells[a] = (f"closed {bars.at[t, a]:.2f} below {p.exit_len}-bar avg "
                          f"{sma_exit.at[t, a]:.2f} -> trend broken")

    if len(held) - len(d.sells) < p.slots:
        cands = []
        for a in bars.columns:
            if a in held:
                continue
            c, s, e, m = bars.at[t, a], sma.at[t, a], ema.at[t, a], mom.at[t, a]
            prev = bars[a].shift(1).at[t]
            if pd.notna(s) and pd.notna(m) and c > s and m > 0 and dipped.at[t, a] and c > e and c > prev:
                cands.append((m, a, c, s, e))
        if cands:
            m, a, c, s, e = max(cands)
            others = ", ".join(x[1] for x in sorted(cands, reverse=True)[1:]) or "none"
            d.buy = a
            d.buy_why = (f"uptrend ({c:.2f} > {p.trend_len}-bar avg {s:.2f}, 12m {m:+.0%}); "
                         f"dipped to {p.ema_len}-bar avg then closed back above it ({e:.2f}) and up on the bar; "
                         f"strongest trend (also qualified: {others})")
    return d
