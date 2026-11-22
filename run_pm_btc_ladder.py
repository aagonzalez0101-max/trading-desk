"""PM-4: Kalshi hourly BTC ladders (KXBTCD) vs the desk's BTC odds model (pre-declared in results/sweep_log.csv).
The model is strategies/btc_odds.py's method re-run AS OF each decision minute (only Coinbase candles before it).
    python run_pm_btc_ladder.py fetch [days]
    python run_pm_btc_ladder.py
"""
import collections, csv, json, math, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np

from core.backtest import report, tstat
from run_pm_sharp_study import get, ts

K = "https://api.elections.kalshi.com/trade-api/v2"
OUT = "data/pm_btcd"
LEAD, BAND, EDGE, SLIP = 30, 0.015, 0.04, 0.01


def coinbase():
    t, p = [], []
    for r in csv.reader(open("data/btc_1m.csv")):
        t.append(int(r[0])); p.append(float(r[1]))
    t = np.array(t); p = np.array(p)
    grid = np.arange(t.min(), t.max() + 60, 60)
    g = np.full(len(grid), np.nan); g[(t - t.min()) // 60] = p
    return grid, g


GRID, PX = coinbase()


def at(tsec):
    i = int((tsec - GRID[0]) // 60)
    return i if 0 <= i < len(GRID) else None


def model(D, strikes, h=LEAD):
    """P(Coinbase close at D+h min > strike) using only candles before D (btc_odds.py method)."""
    i = at(D - 60)                                  # last completed minute before the decision
    if i is None or np.isnan(PX[i]):
        return None
    j0 = max(0, i - 365 * 1440)
    seg = PX[j0:i + 1]
    lr = np.diff(np.log(seg)); lr = lr[~np.isnan(lr)]
    sd_year = np.sqrt(np.mean(lr ** 2)); rec = lr[-60:]; sd_now = np.sqrt(np.mean(rec ** 2))
    scale = 0.5 + 0.5 * sd_now / sd_year
    step = max(1, h // 5)
    a = seg[:-h:step]; b = seg[h::step][:len(a)]
    mv = np.log(b / a); mv = np.sort(mv[~np.isnan(mv)] * scale)
    spot = PX[i]
    return spot, {k: 1 - np.searchsorted(mv, math.log(k / spot), side="right") / len(mv) for k in strikes}


def fetch(days=14):
    os.makedirs(OUT, exist_ok=True)
    mf = os.path.join(OUT, "markets.json")
    if os.path.exists(mf):
        ms = json.load(open(mf))
    else:
        ms, cur = [], None
        hi = int(time.time()) - 3600; lo = hi - days * 86400
        while True:
            p = dict(series_ticker="KXBTCD", status="settled", limit=1000, min_close_ts=lo, max_close_ts=hi)
            if cur:
                p["cursor"] = cur
            j = get(K + "/markets", **p)
            ms += [{k: m.get(k) for k in ("ticker", "event_ticker", "floor_strike", "close_time", "result")} for m in j.get("markets", [])]
            cur = j.get("cursor")
            if not cur or not j.get("markets"):
                break
        json.dump(ms, open(mf, "w"))
    ev = collections.defaultdict(list)
    for m in ms:
        ev[m["event_ticker"]].append(m)
    print("hourly events", len(ev), "markets", len(ms))
    jobs = []
    for e, mm in ev.items():
        T = ts(mm[0]["close_time"]); D = T - LEAD * 60
        i = at(D - 60)
        if i is None or np.isnan(PX[i]):
            continue
        spot = PX[i]
        jobs += [(m, D) for m in mm if m["floor_strike"] and abs(m["floor_strike"] / spot - 1) <= BAND]

    def one(job):
        m, D = job
        f = os.path.join(OUT, m["ticker"] + ".json")
        if os.path.exists(f):
            return
        j = get(f"{K}/series/KXBTCD/markets/{m['ticker']}/candlesticks", start_ts=int(D - 360), end_ts=int(D), period_interval=1)
        c = [(x["end_period_ts"], (x.get("yes_ask") or {}).get("close_dollars"), (x.get("yes_bid") or {}).get("close_dollars"))
             for x in (j or {}).get("candlesticks", [])]
        json.dump(c, open(f, "w"))
    print("candle jobs", len(jobs))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, jobs))


def fee(c):
    return 0.07 * c * (1 - c)


def run(edge=EDGE, stale=0):
    ms = json.load(open(os.path.join(OUT, "markets.json")))
    ev = collections.defaultdict(list)
    for m in ms:
        ev[m["event_ticker"]].append(m)
    out = []
    for e, mm in sorted(ev.items()):
        T = ts(mm[0]["close_time"]); D = T - LEAD * 60
        quotes = {}
        for m in mm:
            f = os.path.join(OUT, m["ticker"] + ".json")
            if not os.path.exists(f):
                continue
            c = [x for x in json.load(open(f)) if D - 300 <= x[0] <= D and x[1] is not None and x[2] is not None]
            if c:
                quotes[m["floor_strike"]] = (float(c[-1][1]), float(c[-1][2]), m["result"])
        if not quotes:
            continue
        mo = model(D - stale * 60, list(quotes), h=LEAD + stale)
        if not mo:
            continue
        spot, P = mo
        for k, (ask, bid, res) in quotes.items():
            p = P[k]
            if 0.02 <= ask <= 0.98 and p - ask - fee(ask) - SLIP >= edge:
                out.append(dict(ev=e, T=T, k=k, side="YES", p=p, c=ask, net=(1 - ask if res == "yes" else -ask) - fee(ask) - SLIP))
            na = 1 - bid
            if 0.02 <= na <= 0.98 and (1 - p) - na - fee(na) - SLIP >= edge:
                out.append(dict(ev=e, T=T, k=k, side="NO", p=1 - p, c=na, net=(1 - na if res == "no" else -na) - fee(na) - SLIP))
    return out


def per_hour(tr):
    h = collections.defaultdict(float)
    for t in tr:
        h[(t["T"], t["ev"])] += t["net"]
    keys = sorted(h)
    return [h[k] for k in keys], [k[0] for k in keys]


def main():
    tr = run()
    print("PM-4 trades %d over %d hours (YES %d / NO %d)" % (len(tr), len({t['ev'] for t in tr}),
          sum(t["side"] == "YES" for t in tr), sum(t["side"] == "NO" for t in tr)))
    if not tr:
        return
    print("  per strike: net $%+.2f avg %+.4f won %.1f%% vs model-expected %.1f%%, avg price %.3f" % (
        sum(t["net"] for t in tr), np.mean([t["net"] for t in tr]), 100 * np.mean([t["net"] > 0 for t in tr]),
        100 * np.mean([t["p"] for t in tr]), np.mean([t["c"] for t in tr])))
    for s in ("YES", "NO"):
        v = [t["net"] for t in tr if t["side"] == s]
        if v:
            print("  %s n=%d net $%+.2f avg %+.4f" % (s, len(v), sum(v), np.mean(v)))
    nets, keys = per_hour(tr)
    report("PM-4 kalshi_btc_hourly_vs_model, PER-HOUR totals ($ per 1 contract each)", nets, keys)
    for e in (0.032, 0.048):
        n2, _ = per_hour(run(e)); print("  edge >= %.1fc: hours %d net $%+.2f t %+.2f" % (100 * e, len(n2), sum(n2), tstat(n2)))
    n3, _ = per_hour(run(stale=60)); print("  placebo (60-min-stale spot): hours %d net $%+.2f t %+.2f" % (len(n3), sum(n3), tstat(n3)))
    d = collections.defaultdict(float)
    for t in tr:
        d[time.strftime("%Y-%m-%d", time.gmtime(t["T"]))] += t["net"]
    print("  days %d; drop best 2 days: $%+.2f -> $%+.2f" % (len(d), sum(d.values()), sum(d.values()) - sum(sorted(d.values())[-2:])))


if __name__ == "__main__":
    fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 14) if "fetch" in sys.argv else main()
