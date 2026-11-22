"""Round 3 of the pre-registered day-trading research (rules: research/DAYTRADE_PLAN.md).

R3-1  volatility breakout, 13 forex pairs, hourly bars 2015-now
R3-2  pre-Fed-announcement drift on SPY, Alpaca 30-minute bars 2016-now
"""
from datetime import date, datetime

import numpy as np
import pandas as pd

from bot.data import CACHE, OUT, PAIRS
from run_daytrade_research import MAX_LEV, RISK, SPLIT, Bars, stats
from run_intraday_momentum import bars as spy_bars

# Scheduled FOMC meetings (second day = announcement day, 2:00pm ET), from federalreserve.gov.
FOMC_ANNOUNCE = """
2016-01-27 2016-03-16 2016-04-27 2016-06-15 2016-07-27 2016-09-21 2016-11-02 2016-12-14
2017-02-01 2017-03-15 2017-05-03 2017-06-14 2017-07-26 2017-09-20 2017-11-01 2017-12-13
2018-01-31 2018-03-21 2018-05-02 2018-06-13 2018-08-01 2018-09-26 2018-11-08 2018-12-19
2019-01-30 2019-03-20 2019-05-01 2019-06-19 2019-07-31 2019-09-18 2019-10-30 2019-12-11
2020-01-29 2020-04-29 2020-06-10 2020-07-29 2020-09-16 2020-11-05 2020-12-16
2021-01-27 2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15
2022-01-26 2022-03-16 2022-05-04 2022-06-15 2022-07-27 2022-09-21 2022-11-02 2022-12-14
2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13
2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18
2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10
2026-01-28 2026-03-18 2026-04-29 2026-06-17 2026-07-29 2026-09-16
""".split()


def r3_1_vol_breakout(b: Bars) -> list:
    out = []
    day = b.t.normalize()
    starts = np.flatnonzero(b.t.hour == 0)
    prev_rng = None
    for s in starts:
        d = day[s]
        idx = np.arange(s, len(b.t))
        idx = idx[(day[idx] == d)]
        if b.t[s].dayofweek >= 5 or len(idx) < 20:
            prev_rng = None
            continue
        rng_today = b.h[idx].max() - b.l[idx].min()
        if prev_rng is None or prev_rng <= 0:
            prev_rng = rng_today
            continue
        o, half = b.o[s], 0.5 * prev_rng
        up, dn = o + half, o - half
        exit_i = next((k for k in idx if b.t[k].hour >= 21), None)
        prev_rng = rng_today
        if exit_i is None:
            continue
        trade = None
        for k in idx[b.t[idx].hour < 21]:
            hit_up, hit_dn = b.h[k] >= up, b.l[k] <= dn
            if hit_up and hit_dn:
                break                                       # ambiguous: skip the day
            if hit_up or hit_dn:
                side = 1 if hit_up else -1
                level = up if hit_up else dn
                entry = max(level, b.o[k]) if side == 1 else min(level, b.o[k])
                stop = o
                exit_px, reason = b.o[exit_i], "time"
                for j in range(k, exit_i):
                    # On the entry bar, only count the stop if the bar also traded back through it.
                    if (side == 1 and b.l[j] <= stop) or (side == -1 and b.h[j] >= stop):
                        exit_px, reason = stop, "stop"
                        break
                lev = min(RISK / (abs(entry - stop) / entry), MAX_LEV)
                pnl = side * (exit_px - entry) - b.cost
                trade = {"pair": b.pair, "time": b.t[k], "side": side, "reason": reason,
                         "net_pips": pnl / b.pip, "ret": lev * pnl / entry, "hours": exit_i - k}
                break
        if trade:
            out.append(trade)
    return out


def r3_2_pre_fomc() -> pd.DataFrame:
    df = spy_bars()
    ny = df.copy()
    ny.index = ny.index.tz_convert("America/New_York")
    px = ny[ny.index.strftime("%H:%M") == "13:30"].close        # close of 13:30-14:00 bar... see below
    # The 13:30 bar closes at 13:59:59, i.e. the last price before the 2:00pm statement.
    px.index = px.index.normalize().tz_localize(None)
    days = px.index
    rows = []
    for a in FOMC_ANNOUNCE:
        a = pd.Timestamp(a)
        if a not in days:
            continue
        prev = days[days < a]
        if not len(prev):
            continue
        p0, p1 = px[prev[-1]], px[a]
        rows.append({"date": a, "ret": p1 / p0 - 1 - 0.0002})
    return pd.DataFrame(rows).set_index("date")


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    fmt = {"$100_becomes": "${:,.2f}".format, "win_rate": "{:.0%}".format, "worst_drop": "{:.1%}".format,
           "avg_net_pips": "{:+.2f}".format, "t_stat": "{:+.2f}".format}

    bars = {p: Bars(p) for p in PAIRS if (CACHE / f"{p}_H1.csv").exists()}
    tr = pd.DataFrame([x for b in bars.values() for x in r3_1_vol_breakout(b)])
    tr.to_csv(OUT / "round3_volbreak_trades.csv", index=False)
    s_in, s_out = stats(tr[tr.time < SPLIT]), stats(tr[tr.time >= SPLIT])
    ok1 = (s_in.get("t_stat", 0) >= 2 and s_in.get("worst_drop", -1) > -0.25 and
           s_out.get("t_stat", 0) >= 1 and s_out.get("worst_drop", -1) > -0.25)
    r1 = pd.DataFrame([{"period": "2015-2021", **s_in}, {"period": "2022-now", **s_out}])
    print("R3-1 volatility breakout (13 pairs):")
    print(r1.to_string(index=False, formatters=fmt))
    print("R3-1 VERDICT:", "PASS" if ok1 else "FAIL", f"| exits: {tr.reason.value_counts().to_dict()}")

    f = r3_2_pre_fomc()
    t_all = f.ret.mean() / f.ret.std() * np.sqrt(len(f))
    halves = {"2016-2020": f[f.index < "2021-01-01"].ret, "2021-now": f[f.index >= "2021-01-01"].ret}
    ok2 = t_all >= 2 and all(h.mean() > 0 for h in halves.values())
    rows = [{"period": k, "events": len(h), "avg_%": 100 * h.mean(), "win_rate": (h > 0).mean(),
             "t_stat": h.mean() / h.std() * np.sqrt(len(h)), "$100_becomes": 100 * (1 + h).prod()} for k, h in halves.items()]
    rows.append({"period": "ALL", "events": len(f), "avg_%": 100 * f.ret.mean(), "win_rate": (f.ret > 0).mean(),
                 "t_stat": t_all, "$100_becomes": 100 * (1 + f.ret).prod()})
    r2 = pd.DataFrame(rows)
    print("\nR3-2 pre-Fed drift on SPY (scheduled FOMC, 1:59pm day before -> 1:59pm announcement day):")
    print(r2.to_string(index=False, formatters={**fmt, "avg_%": "{:+.3f}".format}))
    print("R3-2 VERDICT:", "PASS" if ok2 else "FAIL")

    pd.concat([r1.assign(test="R3-1 vol breakout"), r2.assign(test="R3-2 pre-FOMC drift")]).to_csv(OUT / "round3_research.csv", index=False)
    log = OUT / "sweep_log.csv"
    entries = [{"variant": f"round3_volbreak [{r['period']}]", "pairs": len(bars), "trades": r.get("trades"),
                "win_rate": r.get("win_rate"), "total_return": r.get("$100_becomes", 100) / 100 - 1,
                "max_drawdown": r.get("worst_drop")} for r in r1.to_dict("records")]
    entries += [{"variant": f"round3_preFOMC_SPY [{r['period']}]", "pairs": 1, "trades": r["events"],
                 "win_rate": r["win_rate"], "total_return": r["$100_becomes"] / 100 - 1} for r in rows]
    pd.DataFrame([{"time": datetime.now().isoformat(timespec="seconds"), **e} for e in entries]
                 ).reindex(columns=pd.read_csv(log, nrows=0).columns).to_csv(log, mode="a", header=False, index=False)
