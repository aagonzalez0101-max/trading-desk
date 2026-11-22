"""Run the six pre-registered day-trading tests in research/DAYTRADE_PLAN.md.

Rules live in that file and were written before this ran. One simulator for all six:
fill at bar opens, stop-before-target when both hit in one hour, costs on every trade,
1% risk sizing capped at 20:1, $100 start, training 2015-2021 vs final exam 2022-now.
"""
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf


from bot.data import CACHE, OUT, PAIRS, SPREAD_PIPS, load_hourly, pip_size
from bot.data import OUT

SPLIT = pd.Timestamp("2022-01-01", tz="UTC")
RISK, MAX_LEV = 0.01, 20.0
USD_PAIRS = {"EUR_USD": 1, "GBP_USD": 1, "AUD_USD": 1, "NZD_USD": 1, "USD_JPY": -1, "USD_CAD": -1, "USD_CHF": -1}
HOME = {"JPY": "asia", "AUD": "asia", "NZD": "asia", "EUR": "europe", "GBP": "europe", "CHF": "europe",
        "USD": "america", "CAD": "america"}
SESSIONS = [("asia", 0, 7), ("europe", 7, 13), ("america", 13, 24)]  # start hour, exit hour (UTC)


class Bars:
    def __init__(self, pair):
        df = load_hourly(pair)
        self.pair, self.t = pair, df.index
        self.o, self.h, self.l, self.c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
        self.pip = pip_size(pair)
        self.cost = (SPREAD_PIPS[pair] * 1.2 + 0.5) * self.pip
        r = np.diff(np.log(self.c), prepend=np.log(self.c[0]))
        self.hour_sd = pd.Series(r).rolling(60 * 24, min_periods=24 * 20).std().shift(1).to_numpy()

    def at_or_after(self, ts):
        return int(np.searchsorted(self.t, ts))


def trade(b: Bars, e, side, stop=None, target=None, exit_i=None, cost_mult=1.0):
    """Enter at the open of bar e. Exit at stop/target (checked on bar e onward) or at the open of bar exit_i."""
    n = len(b.c)
    if e >= n or exit_i is None or exit_i <= e or exit_i >= n:
        return None
    entry = b.o[e]
    if stop is not None and not ((side == 1 and stop < entry) or (side == -1 and stop > entry)):
        return None
    if target is not None and not ((side == 1 and target > entry) or (side == -1 and target < entry)):
        return None
    exit_px, reason, j = b.o[exit_i], "time", exit_i
    for k in range(e, exit_i):
        hit_s = stop is not None and (b.l[k] <= stop if side == 1 else b.h[k] >= stop)
        hit_t = target is not None and (b.h[k] >= target if side == 1 else b.l[k] <= target)
        if hit_s:
            gap = b.o[k] if k > e else entry
            exit_px = min(stop, gap) if side == 1 else max(stop, gap)
            reason, j = "stop", k
            break
        if hit_t:
            exit_px, reason, j = target, "target", k
            break
    if stop is not None:
        lev = RISK / (abs(entry - stop) / entry)
    else:
        sd = b.hour_sd[e] * np.sqrt(exit_i - e)
        if not np.isfinite(sd) or sd <= 0:
            return None
        lev = RISK / sd
    lev = min(lev, MAX_LEV)
    pnl = side * (exit_px - entry) - b.cost * cost_mult
    return {"pair": b.pair, "time": b.t[e], "side": side, "reason": reason, "net_pips": pnl / b.pip,
            "ret": lev * pnl / entry, "hours": j - e}


# ---------------------------------------------------------------- the six tests
def h1_home_hours(b: Bars):
    base, quote = b.pair[:3], b.pair[4:]
    out = []
    for name, start, end in SESSIONS:
        home_base, home_quote = HOME[base] == name, HOME[quote] == name
        if home_base == home_quote:
            continue
        side = -1 if home_base else 1                 # sell the home currency
        idx = np.flatnonzero((b.t.hour == start) & (b.t.dayofweek < 5))
        for e in idx:
            x = b.at_or_after(b.t[e] + pd.Timedelta(hours=end - start))
            if x < len(b.t) and b.t[x] - b.t[e] <= pd.Timedelta(hours=end - start + 2):  # skip weekend holds
                out.append(trade(b, e, side, exit_i=x))
    return out


def h2_month_end(b: Bars, eq_mtd: pd.Series):
    if b.pair not in USD_PAIRS:
        return []
    lon = b.t.tz_convert("Europe/London")
    days = pd.Series(lon.normalize().tz_localize(None), index=range(len(lon)))
    wk = days[lon.dayofweek < 5]
    last_days = wk.groupby(wk.dt.to_period("M")).max()
    out = []
    for d in last_days:
        if d not in eq_mtd.index or pd.isna(eq_mtd[d]):
            continue
        e = np.flatnonzero((days == d).to_numpy() & (lon.hour == 11))
        x = np.flatnonzero((days == d).to_numpy() & (lon.hour == 16))
        if len(e) and len(x):
            short_usd = eq_mtd[d] > 0                  # US stocks beat foreign -> USD sold at the fix
            side = USD_PAIRS[b.pair] * (1 if short_usd else -1)
            out.append(trade(b, e[0], side, exit_i=x[0]))
    return out


def h3_round_bounce(b: Bars):
    step, pip, out, used, busy_until = 100 * b.pip, b.pip, [], set(), -1
    for t in range(1, len(b.c) - 1):
        if t <= busy_until or not (7 <= b.t[t].hour <= 20):
            continue
        c0 = b.c[t - 1]
        up, dn = np.ceil(c0 / step - 1e-9) * step, np.floor(c0 / step + 1e-9) * step
        day = b.t[t].date()
        if c0 <= up - 5 * pip and b.h[t] >= up and b.c[t] < up and (day, up) not in used:
            r = trade(b, t + 1, -1, stop=up + 15 * pip, target=b.o[t + 1] - 20 * pip, exit_i=min(t + 7, len(b.c) - 1))
            used.add((day, up))
        elif c0 >= dn + 5 * pip and b.l[t] <= dn and b.c[t] > dn and (day, dn) not in used:
            r = trade(b, t + 1, 1, stop=dn - 15 * pip, target=b.o[t + 1] + 20 * pip, exit_i=min(t + 7, len(b.c) - 1))
            used.add((day, dn))
        else:
            continue
        if r:
            out.append(r)
            busy_until = t + 1 + r["hours"]
    return out


def h4_round_break(b: Bars):
    step, pip, out, busy_until = 100 * b.pip, b.pip, [], -1
    for t in range(1, len(b.c) - 1):
        if t <= busy_until or not (7 <= b.t[t].hour <= 20):
            continue
        c0, c1 = b.c[t - 1], b.c[t]
        up = np.floor((c1 - 10 * pip) / step + 1e-9) * step
        dn = np.ceil((c1 + 10 * pip) / step - 1e-9) * step
        if c0 < up <= c1 - 10 * pip:
            r = trade(b, t + 1, 1, stop=up - 10 * pip, target=b.o[t + 1] + 30 * pip, exit_i=min(t + 9, len(b.c) - 1))
        elif c0 > dn >= c1 + 10 * pip:
            r = trade(b, t + 1, -1, stop=dn + 10 * pip, target=b.o[t + 1] - 30 * pip, exit_i=min(t + 9, len(b.c) - 1))
        else:
            continue
        if r:
            out.append(r)
            busy_until = t + 1 + r["hours"]
    return out


def h5_london_breakout(b: Bars):
    out = []
    dates = pd.Series(b.t.normalize(), index=range(len(b.t)))
    for d, grp in dates.groupby(dates):
        idx = grp.index.to_numpy()
        hours = b.t[idx].hour
        asia = idx[hours <= 6]
        if len(asia) < 5 or b.t[idx[0]].dayofweek >= 5:
            continue
        hi, lo = b.h[asia].max(), b.l[asia].min()
        width = hi - lo
        if not (15 * b.pip <= width <= 60 * b.pip):
            continue
        x = b.at_or_after(d + pd.Timedelta(hours=16))
        for t in idx[(hours >= 7) & (hours <= 10)]:
            if b.c[t] > hi:
                out.append(trade(b, t + 1, 1, stop=lo, target=b.o[t + 1] + width, exit_i=x))
                break
            if b.c[t] < lo:
                out.append(trade(b, t + 1, -1, stop=hi, target=b.o[t + 1] - width, exit_i=x))
                break
    return out


def h6_weekend_gap(b: Bars):
    out = []
    gaps = np.flatnonzero((b.t[1:] - b.t[:-1]) > pd.Timedelta(hours=24)) + 1
    for e in gaps:
        fri = b.c[e - 1]
        gap = b.o[e] - fri
        if abs(gap) < 15 * b.pip:
            continue
        side = -int(np.sign(gap))
        out.append(trade(b, e, side, stop=b.o[e] + np.sign(gap) * abs(gap), target=fri,
                         exit_i=min(e + 24, len(b.c) - 1), cost_mult=3.0))
    return out


def equity_mtd_gap() -> pd.Series:
    """SPY minus EFA month-to-date return through the PREVIOUS day's close, indexed by date."""
    px = yf.download(["SPY", "EFA"], start="2014-11-01", auto_adjust=True, progress=False)["Close"].dropna()
    px.index = px.index.tz_localize(None)
    prev_month_end = px.shift(1).where(px.index.to_period("M") != pd.Series(px.index, index=px.index).shift(1).dt.to_period("M"))
    base = prev_month_end.ffill()
    mtd_prev = (px.shift(1) / base) - 1             # through yesterday's close
    gap = mtd_prev["SPY"] - mtd_prev["EFA"]
    cal = pd.date_range(gap.index[0], gap.index[-1] + pd.Timedelta(days=7))
    return gap.reindex(cal).ffill()


def stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"trades": 0}
    tr = tr.sort_values("time")
    eq = 100 * (1 + tr.ret).cumprod()
    t = tr.ret.mean() / tr.ret.std() * np.sqrt(len(tr)) if tr.ret.std() > 0 else 0
    return {"trades": len(tr), "win_rate": (tr.net_pips > 0).mean(), "avg_net_pips": tr.net_pips.mean(),
            "t_stat": t, "$100_becomes": eq.iloc[-1], "worst_drop": (eq / eq.cummax() - 1).min()}


if __name__ == "__main__":
    bars = {p: Bars(p) for p in PAIRS if (CACHE / f"{p}_H1.csv").exists()}
    mtd = equity_mtd_gap()
    tests = {"H1 home-hours": h1_home_hours, "H2 month-end fix": lambda b: h2_month_end(b, mtd),
             "H3 round bounce": h3_round_bounce, "H4 round break": h4_round_break,
             "H5 London breakout": h5_london_breakout, "H6 weekend gap": h6_weekend_gap}
    rows, verdict = [], {}
    for name, fn in tests.items():
        tr = pd.DataFrame([r for b in bars.values() for r in fn(b) if r])
        tr.to_csv(OUT / f"daytrade_{name.split()[0]}_trades.csv", index=False)
        s_in, s_out = stats(tr[tr.time < SPLIT]), stats(tr[tr.time >= SPLIT])
        ok = (s_in.get("t_stat", 0) >= 2 and s_in.get("avg_net_pips", 0) > 0 and s_in.get("worst_drop", -1) > -0.25
              and s_out.get("t_stat", 0) >= 1 and s_out.get("avg_net_pips", 0) > 0 and s_out.get("worst_drop", -1) > -0.25)
        verdict[name] = "PASS" if ok else "FAIL"
        for label, s in (("2015-2021", s_in), ("2022-now", s_out)):
            rows.append({"test": name, "period": label, **s, "verdict": verdict[name]})
        print(f"{name}: {verdict[name]}", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "daytrade_research.csv", index=False)
    log = OUT / "sweep_log.csv"
    pd.DataFrame([{"time": datetime.now().isoformat(timespec="seconds"), "variant": f"daytrade_{r['test']} [{r['period']}]",
                   "pairs": len(bars), "trades": r.get("trades"), "win_rate": r.get("win_rate"),
                   "total_return": r.get("$100_becomes", 100) / 100 - 1, "max_drawdown": r.get("worst_drop")} for r in rows]
                 ).reindex(columns=pd.read_csv(log, nrows=0).columns).to_csv(log, mode="a", header=False, index=False)
    pd.set_option("display.width", 220)
    print(res.to_string(index=False, formatters={"$100_becomes": "${:,.2f}".format, "win_rate": "{:.0%}".format,
                                                 "worst_drop": "{:.1%}".format, "avg_net_pips": "{:+.2f}".format,
                                                 "t_stat": "{:+.2f}".format}))
