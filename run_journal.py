"""Trade journal from $100 for the weekly and daily (fast) versions of our strategy.

In-sample 2007-2016 vs out-of-sample 2017-now, each starting from $100.
Journals saved to results/journal_<version>_<period>.csv
"""
import numpy as np

from bot.etf import load
from bot.journal import DAILY, WEEKLY, run
from bot.data import OUT

PERIODS = [("2007-2016", "2007-01-01", "2017-01-01"), ("2017-now", "2017-01-01", None)]


def summary(trades, eq):
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    dd = (eq / eq.cummax() - 1).min()
    wins = (trades["pnl_$"] > 0).mean() if len(trades) else np.nan
    return (f"${eq.iloc[0]:.0f} -> ${eq.iloc[-1]:.2f} | {(eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1:+.1%}/yr | "
            f"worst drop {dd:.1%} | {len(trades)} closed trades ({len(trades) / years:.0f}/yr) | win {wins:.0%}")


if __name__ == "__main__":
    px = load()
    for p in (WEEKLY, DAILY):
        print(f"\n=== {p.name} ===")
        for label, lo, hi in PERIODS:
            data = px[px.index < hi] if hi else px
            trades, eq, open_now = run(data, p, 100.0, start=lo)
            print(f"  {label}: {summary(trades, eq)}")
            trades.to_csv(OUT / f"journal_{p.freq}_{label}.csv", index=False)
            if hi is None and open_now:
                print("  still open:", [(o["ETF"], str(o["bought"]), f"{o['open_pnl_%']:+}%") for o in open_now])
