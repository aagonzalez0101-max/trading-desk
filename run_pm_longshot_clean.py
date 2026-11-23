"""PM-8c: Kalshi longshot test with NO look-ahead in the sample (pre-declared in results/sweep_log.csv).
PM-8 selected markets by LIFETIME volume (includes trading after the decision) -> biased toward longshots that came alive. Here the
liquidity filter is volume traded in the 24h BEFORE the decision. (Lifetime >= 500 is used only to skip dead markets: pre-decision
volume can never exceed lifetime volume, so that drops nothing the rule could trade.)
    python run_pm_longshot_clean.py fetch
    python run_pm_longshot_clean.py
"""
import collections, json, os, random, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np

from core.backtest import report, tstat
from run_pm_sharp_study import get, ts
import run_pm_longshot as OLD

K = "https://api.elections.kalshi.com/trade-api/v2"
OUT = "data/pm_longshot_c"
PREVOL, LEAD, SLIP = 500, 24 * 3600, 0.01


def fetch(days=30):
    os.makedirs(os.path.join(OUT, "c"), exist_ok=True)
    mf = os.path.join(OUT, "markets.json")
    if not os.path.exists(mf):
        hi = int(time.time()); lo = hi - days * 86400
        ser = [x["ticker"] for x in (get(K + "/series") or {}).get("series", [])
               if x.get("category") != "Crypto" and x.get("frequency") not in ("hourly", "fifteen_min")]
        print("series", len(ser), flush=True)

        def one_series(st):
            out, cur = [], None
            for _ in range(80):
                p = dict(series_ticker=st, status="settled", limit=1000, min_close_ts=lo, max_close_ts=hi)
                if cur:
                    p["cursor"] = cur
                j = get(K + "/markets", **p) or {}
                for m in j.get("markets", []):
                    try:
                        v = float(m.get("volume_fp") or 0)
                    except ValueError:
                        v = 0
                    if v >= PREVOL and m.get("market_type") == "binary" and m.get("result") in ("yes", "no"):
                        out.append({k: m.get(k) for k in ("ticker", "event_ticker", "result", "open_time", "close_time")})
                cur = j.get("cursor")
                if not cur or not j.get("markets"):
                    break
            return out
        ms = []
        with ThreadPoolExecutor(8) as ex:
            for i, r in enumerate(ex.map(one_series, ser)):
                ms += r
                if i % 2000 == 0:
                    print(" series", i, "markets", len(ms), flush=True)
        json.dump(ms, open(mf, "w"))
    ms = sample(json.load(open(mf)))
    print("sampled markets", len(ms), "events", len({m["event_ticker"] for m in ms}), flush=True)

    def one(m):
        f = os.path.join(OUT, "c", m["ticker"].replace("/", "_") + ".json")
        if os.path.exists(f):
            return
        T = ts(m["close_time"]) - LEAD
        j = get(f"{K}/series/{m['event_ticker'].split('-')[0]}/markets/{m['ticker']}/candlesticks",
                start_ts=int(T - 24 * 3600), end_ts=int(T + 3600), period_interval=60)
        c = [(x["end_period_ts"], (x.get("yes_ask") or {}).get("close_dollars"), (x.get("yes_bid") or {}).get("close_dollars"),
              float(x.get("volume_fp") or 0)) for x in (j or {}).get("candlesticks", [])]
        json.dump(c, open(f, "w"))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, ms))


def sample(ms, share=0.15, seed=9):
    """fresh seeded 15% of events, DISJOINT from PM-8's seed-8 sample."""
    ms = [m for m in ms if ts(m["close_time"]) - ts(m["open_time"]) > LEAD + 3600]
    ev = sorted({m["event_ticker"] for m in ms})
    old = set(random.Random(8).sample(ev, int(len(ev) * 0.15)))       # same construction as PM-8 (overlap is removed)
    rest = [e for e in ev if e not in old]
    keep = set(random.Random(seed).sample(rest, int(len(ev) * share)))
    return [m for m in ms if m["event_ticker"] in keep]


def fee(c):
    return 0.07 * c * (1 - c)


def run(lo=0.005, hi=0.10, side="NO"):
    ms = sample(json.load(open(os.path.join(OUT, "markets.json"))))
    out, bk = [], []
    for m in ms:
        f = os.path.join(OUT, "c", m["ticker"].replace("/", "_") + ".json")
        if not os.path.exists(f):
            continue
        T = ts(m["close_time"]) - LEAD
        c = json.load(open(f))
        pre = sum(x[3] for x in c if x[0] <= T)
        q = [x for x in c if T - 3600 <= x[0] <= T and x[1] and x[2]]
        if pre < PREVOL or not q:
            continue
        ask, bid = float(q[-1][1]), float(q[-1][2])
        bk.append((ask, m["result"] == "yes"))
        if not (lo < ask <= hi):
            continue
        if side == "NO":
            cost = 1 - bid; won = m["result"] == "no"
        else:
            cost = ask; won = m["result"] == "yes"
        if not (0.02 <= cost <= 0.99):
            continue
        out.append(dict(ev=m["event_ticker"], ser=m["event_ticker"].split("-")[0], day=m["close_time"][:10], T=T, cost=cost, won=won,
                        net=(1 - cost if won else -cost) - fee(cost) - SLIP))
    return out, bk


def main():
    tr, bk = run()
    A = np.array([a for a, _ in bk]); Y = np.array([y for _, y in bk])
    print("PM-8c markets with >= %d contracts traded in the 24h before the decision: %d" % (PREVOL, len(bk)))
    for lo, hi in ((0, .03), (.03, .06), (.06, .10), (.10, .20), (.40, .60), (.80, .90), (.90, .97), (.97, 1.0)):
        k = (A > lo) & (A <= hi)
        if k.sum():
            print("  YES ask %2d-%2dc: n=%5d  avg ask %.3f  YES won %.3f" % (100 * lo, 100 * hi, k.sum(), A[k].mean(), Y[k].mean()))
    for name, (t2, lab) in {"rule 1 NO on YES<=10c": (tr, "PM-8c rule 1: BUY NO when YES ask <= 10c"),
                            "rule 2 YES on 5-20c": (run(0.05, 0.20, "YES")[0], "PM-8c rule 2: BUY YES when YES ask 5-20c")}.items():
        print("\n" + name + ": trades %d in %d events" % (len(t2), len({t['ev'] for t in t2})))
        if not t2:
            continue
        print("  per contract net $%+.2f avg %+.4f won %.1f%% at avg cost %.3f" % (
            sum(t["net"] for t in t2), np.mean([t["net"] for t in t2]), 100 * np.mean([t["won"] for t in t2]), np.mean([t["cost"] for t in t2])))
        nets, keys = OLD.per_event(t2)
        report(lab + " (per EVENT totals; needs t >= 2.5 with two rules)", nets, keys)
        d = collections.defaultdict(float)
        for t in t2:
            d[t["day"]] += t["net"]
        print("  drop best 2 days: $%+.2f -> $%+.2f" % (sum(d.values()), sum(d.values()) - sum(sorted(d.values())[-2:])))
    for hi in (0.08, 0.12):
        n2, _ = OLD.per_event(run(hi=hi)[0]); print("  rule 1 cut %dc: events %d net $%+.2f t %+.2f" % (100 * hi, len(n2), sum(n2), tstat(n2)))
    for lo, hi in ((0.04, 0.16), (0.06, 0.24)):
        n2, _ = OLD.per_event(run(lo, hi, "YES")[0]); print("  rule 2 %d-%dc: events %d net $%+.2f t %+.2f" % (100 * lo, 100 * hi, len(n2), sum(n2), tstat(n2)))
    n3, _ = OLD.per_event(run(0.40, 0.60, "NO")[0]); print("  placebo NO on 40-60c: events %d net $%+.2f t %+.2f" % (len(n3), sum(n3), tstat(n3)))


if __name__ == "__main__":
    fetch() if "fetch" in sys.argv else main()
