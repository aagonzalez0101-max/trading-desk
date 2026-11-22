"""P2-F: Connors RSI(2) pullback swing trades on ETFs (pre-declared in results/sweep_log.csv).
Signal on a close, trade at the NEXT open (no look-ahead). Free Yahoo daily data (data/etf_wide_close.csv / _open.csv).
    python run_phase2_rsi2.py
"""
import collections
import numpy as np
import pandas as pd

from core.backtest import report, tstat
import run_phase2_backtest as B

UNI = ["SPY", "QQQ", "IWM", "EFA", "EEM", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB"]
COST = 0.001


def rsi(c, n=2):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def trades(C, O, lvl=10, sma=200, rng=None, n_target=None):
    """-> list of (sym, entry_idx, exit_idx, net). Entries at open i+1 after signal close i; exits at open j+1 after close j > SMA5."""
    out = []
    for s in UNI:
        c, o = C[s], O[s]
        ok = c.notna() & o.notna()
        c, o = c[ok], o[ok]
        r = rsi(c); up = c > c.rolling(sma).mean(); x5 = c > c.rolling(5).mean()
        sig = (up & (r < lvl)).values
        if rng is not None:                       # placebo: random uptrend days, same count as the real signal
            pool = np.flatnonzero(up.values & c.rolling(sma).mean().notna().values)
            k = int(sig.sum()); sig = np.zeros(len(c), bool)
            if k and len(pool):
                sig[rng.choice(pool, size=min(k, len(pool)), replace=False)] = True
        x5 = x5.values; ov = o.values; idx = c.index
        i = 0
        while i < len(c) - 2:
            if sig[i]:
                e = i + 1; j = e
                while j < len(c) - 1 and not x5[j]:
                    j += 1
                if j >= len(c) - 1:
                    break
                x = j + 1
                net = ov[x] / ov[e] * (1 - COST) / (1 + COST) - 1
                out.append((s, idx[e], idx[x], net))
                i = x
            else:
                i += 1
    return out


def portfolio(C, O, tr):
    """14 equal slots; a slot is in its ETF from entry open to exit open, otherwise in BIL. Daily equity."""
    bil = B.load()["BIL"].pct_change().fillna(0)
    dates = C.index[(C.index >= "2002-01-02")]
    ret = pd.DataFrame(0.0, index=dates, columns=UNI)
    held = pd.DataFrame(False, index=dates, columns=UNI)
    for s, e, x, net in tr:
        if e < dates[0]:
            continue
        c, o = C[s], O[s]
        days = c.loc[e:x].index
        for k, d in enumerate(days):
            if d not in ret.index:
                continue
            if k == 0:
                r = c[d] / o[d] - 1 - COST
            elif d == x:
                r = o[d] / c[days[k - 1]] - 1 - COST
            else:
                r = c[d] / c[days[k - 1]] - 1
            ret.loc[d, s] = r
            if d != x:
                held.loc[d, s] = True
    b = bil.reindex(dates).fillna(0)
    # exit day: slot is in the ETF until the open, then cash -> approximate as ETF part only (conservative: no BIL that day)
    daily = (ret.where(ret != 0, np.nan).fillna(0) + (~held & (ret == 0)).astype(float).mul(b, axis=0)).mean(axis=1)
    return (1 + daily).cumprod()


def main():
    C = pd.read_csv("data/etf_wide_close.csv", index_col=0, parse_dates=True)
    O = pd.read_csv("data/etf_wide_open.csv", index_col=0, parse_dates=True)
    C = C[C.index >= "1999-01-01"]; O = O.reindex(C.index)
    tr = trades(C, O)
    nets = [t[3] * 100 for t in tr]; keys = [t[1] for t in tr]
    ok = report("P2-F rsi2_etf per trade (net %, 14 ETFs, 1999-2026)", nets, keys, unit="%")
    post = [t[3] * 100 for t in tr if t[1] >= pd.Timestamp("2009-01-01")]
    print("  post-publication 2009+: n=%d avg %+.3f%% t %+.2f" % (len(post), np.mean(post), tstat(post)))
    print("  avg hold %.1f days, win %.0f%%" % (np.mean([(t[2] - t[1]).days for t in tr]), 100 * np.mean([t[3] > 0 for t in tr])))
    by = collections.defaultdict(list)
    for t in tr:
        by[t[0]].append(t[3] * 100)
    print("  by ETF:", ", ".join("%s %+.2f%%(%d)" % (s, np.mean(v), len(v)) for s, v in by.items()))
    for kw in (dict(lvl=8), dict(lvl=12), dict(sma=160), dict(sma=240)):
        v = [t[3] * 100 for t in trades(C, O, **kw)]
        print("  robust %-12s n=%d avg %+.3f%% t %+.2f" % (kw, len(v), np.mean(v), tstat(v)))
    rng = np.random.default_rng(11)
    pl = [np.mean([t[3] * 100 for t in trades(C, O, rng=rng)]) for _ in range(20)]
    print("  placebo (random uptrend entries, same exit) x20: avg per trade %+.3f%% (95th %+.3f%%) vs real %+.3f%%" % (
        np.mean(pl), np.percentile(pl, 95), np.mean(nets)))
    eq = portfolio(C, O, tr); rf = B.load()["BIL"].pct_change()
    s = B.stats(eq, rf); spy = B.stats((1 + C["SPY"].pct_change().fillna(0))[C.index >= "2002-01-02"].cumprod(), rf)
    print("  portfolio 2002-2026: CAGR %+.1f%% Sharpe %.2f worst DD %.1f%%   (SPY %+.1f%% / %.2f / %.1f%%)" % (
        100 * s["cagr"], s["sharpe"], 100 * s["maxdd"], 100 * spy["cagr"], spy["sharpe"], 100 * spy["maxdd"]))
    for lab, a, b in (("2002-2014", "2002", "2015"), ("2015-2026", "2015", "2027")):
        e2 = eq[(eq.index >= a) & (eq.index < b)]; s2 = B.stats(e2, rf)
        print("    %s: CAGR %+.1f%% Sharpe %.2f DD %.1f%%" % (lab, 100 * s2["cagr"], s2["sharpe"], 100 * s2["maxdd"]))


if __name__ == "__main__":
    main()
