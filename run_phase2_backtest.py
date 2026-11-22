"""PHASE 2 HISTORICAL TESTS -- the pre-declared rules in strategies/phase2.py over 2004-2026 daily data (free, Yahoo).

Mechanics (same for every rule, benchmarks included):
  * decide on each month's last close using only data up to that close; trade at the NEXT trading day's close
    (the paper arena orders after the close and fills at the next open -- the backtest is a few hours later, not earlier)
  * between rebalances the holdings drift with the market (real buy-and-hold inside the month)
  * cost 0.10% of every dollar traded (spread + slippage; Alpaca has no commission)
  * cash earns BIL (T-bill ETF); before BIL existed (2007-05) the 3-month T-bill rate
PASS = core.backtest.report() on monthly net returns AND Sharpe > SPY AND worst drawdown shallower than SPY, plus robustness.
    python run_phase2_backtest.py            # everything, writes results/phase2_backtest.csv + _monthly.csv + sweep_log rows
"""
import csv, datetime, json, sys
import numpy as np
import pandas as pd

from core.backtest import report, tstat, permutation_p
from strategies import phase2 as P

COST = 0.001
START = "2003-12-31"          # first decision day; returns from Jan 2004
SPLIT = "2015-01-01"          # walk-forward: decade 1 = 2004-2014, decade 2 = 2015-2026


def load():
    c = pd.read_csv("data/etf_wide_close.csv", index_col=0, parse_dates=True)
    c = c[c["SPY"].notna()]
    # synthetic BIL before inception, from the 3m T-bill rate (monthly, forward-filled)
    r = pd.read_csv("data/rates_3m.csv", index_col=0, parse_dates=True)["USD"].dropna()
    daily_rf = r.reindex(c.index, method="ffill") / 252
    syn = (1 + daily_rf.fillna(0)).cumprod()
    first = c["BIL"].first_valid_index()
    bil = c["BIL"].copy()
    bil[c.index < first] = syn[c.index < first] * (c.loc[first, "BIL"] / syn[first])
    c["BIL"] = bil
    return c[c.index >= "2002-01-01"]


def simulate(close, rule, start=START, **kw):
    """-> daily equity Series (net of costs), list of (date, turnover)."""
    cols = list(close.columns); idx = {c: i for i, c in enumerate(cols)}
    R = close.pct_change().fillna(0.0).values          # an ETF that doesn't exist yet returns 0 and is never held
    dates = close.index
    month = dates.to_period("M")
    is_me = np.r_[month[1:] != month[:-1], False]       # last trading day of a month (the final, partial month excluded)
    w = np.zeros(len(cols)); w[idx[P.CASH]] = 1.0
    eq = 1.0; out = []; turns = []; pending = None
    i0 = dates.searchsorted(pd.Timestamp(start))
    for d in range(i0, len(dates)):
        if d > i0:
            pr = float(w @ R[d]); eq *= 1 + pr
            w = w * (1 + R[d]) / (1 + pr)
        if pending is not None:                         # execute yesterday's decision at today's close
            tgt = np.zeros(len(cols))
            for a, x in pending.items():
                tgt[idx[a]] = x
            turn = float(np.abs(tgt - w).sum()); eq *= 1 - COST * turn
            turns.append((dates[d], turn)); w = tgt; pending = None
        if is_me[d]:
            pending = rule(close.iloc[max(0, d - 330):d + 1], **kw)      # 330 days > longest lookback (302+1)
        out.append(eq)
    return pd.Series(out, index=dates[i0:]), turns


def stats(eq, rf_daily):
    r = eq.pct_change().dropna(); ex = r - rf_daily.reindex(r.index).fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    dd = (eq / eq.cummax() - 1).min()
    return dict(cagr=(eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1, vol=r.std() * np.sqrt(252),
                sharpe=ex.mean() / ex.std() * np.sqrt(252), maxdd=dd, total=eq.iloc[-1] / eq.iloc[0] - 1)


def monthly(eq):
    m = eq.resample("ME").last()
    return (m.pct_change().dropna() * 100)          # % per month


def main():
    close = load()
    rf = close[P.CASH].pct_change()
    print("data: %d days %s -> %s, %d ETFs" % (len(close), close.index[0].date(), close.index[-1].date(), close.shape[1]))
    res = {}
    for name, rule in P.RULES.items():
        eq, turns = simulate(close, rule)
        res[name] = dict(eq=eq, turns=turns, st=stats(eq, rf), m=monthly(eq),
                         d1=stats(eq[eq.index < SPLIT], rf), d2=stats(eq[eq.index >= SPLIT], rf))
        s = res[name]["st"]
        print("%-14s CAGR %+5.1f%%  vol %4.1f%%  Sharpe %.2f  worst DD %5.1f%%  turnover/yr %.1fx" % (
            name, 100 * s["cagr"], 100 * s["vol"], s["sharpe"], 100 * s["maxdd"],
            sum(t for _, t in turns) / ((eq.index[-1] - eq.index[0]).days / 365.25)))
    spy = res["spy_hold"]["st"]

    # robustness: +-20% on every parameter
    ROB = {"tsmom_etf8": [dict(lookbacks=(50, 101, 202)), dict(lookbacks=(76, 151, 302)), dict(volwin=50), dict(volwin=76),
                          dict(target=0.08), dict(target=0.12)],
           "dual_momentum": [dict(lookback=202), dict(lookback=302)],
           "risk_parity8": [dict(volwin=50), dict(volwin=76)]}
    ROB["tsmom_wide25"] = ROB["tsmom_etf8"]
    rows = []; verdict = {}
    for name in ["tsmom_etf8", "tsmom_wide25", "dual_momentum", "risk_parity8", "sixty_forty"]:
        r = res[name]; s = r["st"]; m = r["m"]
        print("\n" + "=" * 100)
        ok_rep = report("P2 %s monthly net %% (2004-01..2026-11)" % name, list(m.values), list(m.index), unit="%")
        beat = s["sharpe"] > spy["sharpe"] and s["maxdd"] > spy["maxdd"]
        print("  vs SPY: Sharpe %.2f vs %.2f, worst DD %.1f%% vs %.1f%% -> %s" % (s["sharpe"], spy["sharpe"], 100 * s["maxdd"],
              100 * spy["maxdd"], "BEATS" if beat else "does NOT beat"))
        for lab, k in (("2004-2014", "d1"), ("2015-2026", "d2")):
            a, b = r[k], res["spy_hold"][k]
            print("  %s: CAGR %+5.1f%% Sharpe %.2f DD %5.1f%%   (SPY %+5.1f%% / %.2f / %5.1f%%)" % (
                lab, 100 * a["cagr"], a["sharpe"], 100 * a["maxdd"], 100 * b["cagr"], b["sharpe"], 100 * b["maxdd"]))
        drop2 = m.sum() - m.nlargest(2).sum()
        print("  drop best 2 months: total %+.1f%% -> %+.1f%%" % (m.sum(), drop2))
        rob_ok = True
        for kw in ROB.get(name, []):
            eq2, _ = simulate(close, P.RULES[name], **kw); s2 = stats(eq2, rf)
            good = s2["cagr"] > 0 and s2["sharpe"] >= 0.8 * s["sharpe"]
            rob_ok &= good
            print("  robust %-28s CAGR %+5.1f%% Sharpe %.2f DD %5.1f%% %s" % (kw, 100 * s2["cagr"], s2["sharpe"], 100 * s2["maxdd"],
                                                                         "ok" if good else "WEAK"))
        plac = placebo(close, name, rf) if name in ("tsmom_etf8", "tsmom_wide25", "dual_momentum") else None
        plac_ok = True
        if plac is not None:
            pct = (np.array(plac) < s["sharpe"]).mean()
            plac_ok = pct >= 0.95
            print("  placebo (random signal, same sizing) n=%d: Sharpe median %.2f, 95th %.2f; real beats %.0f%% -> %s" % (
                len(plac), np.median(plac), np.percentile(plac, 95), 100 * pct, "ok" if plac_ok else "FAIL"))
        passed = ok_rep and beat and drop2 > 0 and rob_ok and plac_ok
        verdict[name] = passed
        print("  VERDICT %s: %s" % (name, "PASS" if passed else "FAIL"))
        rows.append([datetime.datetime.now().isoformat(timespec="seconds"),
                     "P2 %s %s | Sharpe %.2f vs SPY %.2f, DD %.1f%% vs %.1f%%, t %.2f, perm p %.3f, robust %s, placebo %s, dec1 Sh %.2f dec2 Sh %.2f" % (
                         name, "PASS" if passed else "FAIL", s["sharpe"], spy["sharpe"], 100 * s["maxdd"], 100 * spy["maxdd"],
                         tstat(list(m.values)), permutation_p(list(m.values)), rob_ok, plac_ok if plac is not None else "n/a",
                         r["d1"]["sharpe"], r["d2"]["sharpe"]),
                     "", len(m), (m > 0).mean(), m.mean(), "", s["total"], s["cagr"], s["maxdd"], 12])
    with open("results/sweep_log.csv", "a", newline="") as f:
        csv.writer(f).writerows(rows)
    pd.DataFrame({k: v["m"] for k, v in res.items()}).to_csv("results/phase2_backtest_monthly.csv", float_format="%.4f")
    summ = {k: {**{x: round(float(y), 4) for x, y in v["st"].items()}, "pass": (bool(verdict[k]) if k in verdict else None)} for k, v in res.items()}
    json.dump(summ, open("results/phase2_backtest.json", "w"), indent=1)
    print("\nwrote results/phase2_backtest.json, results/phase2_backtest_monthly.csv, sweep_log rows")


_CLOSE = None


def _plac_one(args):
    """one placebo run (module-level so a process pool can run it)."""
    name, seed, vals, probs = args
    global _CLOSE
    if _CLOSE is None:
        _CLOSE = load()
    rng = np.random.default_rng(seed); rf = _CLOSE[P.CASH].pct_change()
    if name == "dual_momentum":
        rule = lambda c: pd.Series({rng.choice(["SPY", "EFA", "AGG"], p=probs): 1.0})
        return stats(simulate(_CLOSE, rule)[0], rf)["sharpe"]
    sig = lambda s: pd.Series(rng.choice(vals, size=len(s), p=probs), index=s.index)
    return stats(simulate(_CLOSE, P.RULES[name], signal=sig)[0], rf)["sharpe"]


def placebo(close, name, rf, n=200):
    """same machinery, the signal replaced by random draws from the REAL signal's own mix -> how often does luck look this good?"""
    from multiprocessing import Pool
    if name == "dual_momentum":
        seen = []
        orig = P.dual_momentum
        simulate(close, lambda c: (lambda w: (seen.append(w.index[0]), w)[1])(orig(c)))
        vals = np.array(["SPY", "EFA", "AGG"]); probs = np.array([seen.count(v) for v in vals]) / len(seen)
    else:
        seen = []
        def rec(s):
            seen.extend(s.values); return s
        simulate(close, P.RULES[name], signal=rec)
        vals, cnt = np.unique(np.round(seen, 4), return_counts=True); probs = cnt / cnt.sum()
    print("  real signal mix:", dict(zip([str(v) if isinstance(v, str) else round(float(v), 2) for v in vals], np.round(probs, 2))))
    with Pool() as pool:
        return pool.map(_plac_one, [(name, 1000 + i, vals, probs) for i in range(n)])


if __name__ == "__main__":
    main()
