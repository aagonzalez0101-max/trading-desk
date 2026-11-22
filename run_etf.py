"""Backtest long-only ETF trend following. Split fixed BEFORE looking at results:
in-sample 2007-2016, out-of-sample 2017-now."""
import pandas as pd

from bot.etf import (buy_hold, ema_16_64, faber_10m, faber_weekly, load, rotation,
                     simulate, summarize, trend_pullback)

START, SPLIT = "2007-01-01", "2017-01-01"
STRATS = {
    "buy & hold (benchmark)": buy_hold,
    "faber 10-month": faber_10m,
    "trend 16/64 long-only": ema_16_64,
    "A faber weekly": faber_weekly,
    "B rotation 26w": rotation(26),
    "C rotation 52w": rotation(52),
    "OURS trend+pullback": trend_pullback,
}


def row(name, s):
    return (f"  {name:24s} CAGR {s['cagr']:+6.1%} | vol {s['vol']:5.1%} | Sharpe {s['sharpe']:+.2f} | "
            f"maxDD {s['max_dd']:6.1%} | worst yr {s['worst_year']:+6.1%}")


if __name__ == "__main__":
    px = load()
    px = px[px.index >= START]
    print(f"ETFs: {', '.join(px.columns)}  ({px.index[0]:%Y-%m-%d} -> {px.index[-1]:%Y-%m-%d})")
    results = {n: simulate(px, f(px)) for n, f in STRATS.items()}
    for label, lo, hi in [("IN-SAMPLE 2007-2016", START, SPLIT), ("OUT-OF-SAMPLE 2017-now", SPLIT, None)]:
        print(f"\n{label}")
        for n, r in results.items():
            r = r[r.index >= lo] if hi is None else r[(r.index >= lo) & (r.index < hi)]
            print(row(n, summarize(r)))
    yearly = pd.DataFrame({n: r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1)
                           for n, r in results.items()})
    print("\nBy year:")
    print(yearly.map(lambda v: f"{v:+.1%}").to_string())

    print("\nTrades per year (each buy or sell of one ETF = 1 trade):")
    for n, f in STRATS.items():
        sig = f(px)
        trades = (sig.diff().abs() > 0).sum().sum()
        print(f"  {n:24s} {trades / (len(px) / 252):5.1f}")
