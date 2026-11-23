"""PM-8: Kalshi favorite-longshot bias -- buy NO on <=10c YES contracts 24h before close (pre-declared in results/sweep_log.csv).
    python run_pm_longshot.py fetch [days]
    python run_pm_longshot.py
"""
import collections, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np

from core.backtest import report, tstat
from run_pm_sharp_study import get, ts

K = "https://api.elections.kalshi.com/trade-api/v2"
OUT = "data/pm_longshot"
MINVOL, LEAD, SLIP = 5000, 24 * 3600, 0.01


def fetch(days=30):
    os.makedirs(os.path.join(OUT, "c"), exist_ok=True)
    mf = os.path.join(OUT, "markets.json")
    if os.path.exists(mf):
        ms = json.load(open(mf))
    else:
        hi = int(time.time()); lo = hi - days * 86400
        ser = [x["ticker"] for x in (get(K + "/series") or {}).get("series", [])
               if x.get("category") != "Crypto" and x.get("frequency") not in ("hourly", "fifteen_min")]
        print("series", len(ser), flush=True)

        def one_series(st):
            out, cur = [], None
            for _ in range(50):
                p = dict(series_ticker=st, status="settled", limit=1000, min_close_ts=lo, max_close_ts=hi)
                if cur:
                    p["cursor"] = cur
                j = get(K + "/markets", **p) or {}
                for m in j.get("markets", []):
                    try:
                        v = float(m.get("volume_fp") or 0)
                    except ValueError:
                        v = 0
                    if v >= MINVOL and m.get("market_type") == "binary" and m.get("result") in ("yes", "no"):
                        out.append({k: m.get(k) for k in ("ticker", "event_ticker", "result", "open_time", "close_time", "title")} | {"vol": v})
                cur = j.get("cursor")
                if not cur or not j.get("markets"):
                    break
            return out
        ms = []
        with ThreadPoolExecutor(8) as ex:
            for i, r in enumerate(ex.map(one_series, ser)):
                ms += r
                if i % 2000 == 0:
                    print(" series", i, "markets kept", len(ms), flush=True)
        json.dump(ms, open(mf, "w"))
    ms = [m for m in ms if ts(m["close_time"]) - ts(m["open_time"]) > LEAD + 3600]
    ms = sample(ms)
    print("markets kept", len(ms), "events", len({m["event_ticker"] for m in ms}), flush=True)

    def one(m):
        f = os.path.join(OUT, "c", m["ticker"].replace("/", "_") + ".json")
        if os.path.exists(f):
            return
        T = ts(m["close_time"]) - LEAD
        ser = m["event_ticker"].split("-")[0]
        j = get(f"{K}/series/{ser}/markets/{m['ticker']}/candlesticks", start_ts=int(T - 3 * 3600), end_ts=int(T + 3600), period_interval=60)
        c = [(x["end_period_ts"], (x.get("yes_ask") or {}).get("close_dollars"), (x.get("yes_bid") or {}).get("close_dollars"))
             for x in (j or {}).get("candlesticks", [])]
        json.dump(c, open(f, "w"))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, ms))


def sample(ms, share=0.15, seed=8):
    """seeded random share of EVENTS (all markets of a sampled event kept) -- amendment #2, logged before any price was seen."""
    import random
    ev = sorted({m["event_ticker"] for m in ms}); keep = set(random.Random(seed).sample(ev, int(len(ev) * share)))
    return [m for m in ms if m["event_ticker"] in keep]


def fee(c):
    return 0.07 * c * (1 - c)


def run(cut=0.10, band=None):
    ms = sample(json.load(open(os.path.join(OUT, "markets.json"))))
    out = []; buckets = []
    for m in ms:
        f = os.path.join(OUT, "c", m["ticker"].replace("/", "_") + ".json")
        if not os.path.exists(f):
            continue
        T = ts(m["close_time"]) - LEAD
        q = [x for x in json.load(open(f)) if T - 3600 <= x[0] <= T + 3600 and x[1] and x[2]]
        if not q:
            continue
        q = min(q, key=lambda x: abs(x[0] - T))
        ask, bid = float(q[1]), float(q[2])
        buckets.append((ask, m["result"] == "yes"))
        hit = (band[0] <= ask <= band[1]) if band else (0.005 < ask <= cut)
        if not hit:
            continue
        no = 1 - bid
        if not (0.02 <= no <= 0.99):
            continue
        net = (1 - no if m["result"] == "no" else -no) - fee(no) - SLIP
        out.append(dict(ev=m["event_ticker"], ser=m["event_ticker"].split("-")[0], day=m["close_time"][:10], ask=ask, no=no,
                        won=m["result"] == "no", net=net, T=T))
    return out, buckets


def per_event(tr):
    h = collections.defaultdict(float); first = {}
    for t in tr:
        h[t["ev"]] += t["net"]; first[t["ev"]] = min(first.get(t["ev"], 9e18), t["T"])
    k = sorted(h, key=lambda e: first[e])
    return [h[e] for e in k], [first[e] for e in k]


def main():
    tr, bk = run()
    A = np.array([a for a, _ in bk]); Y = np.array([y for _, y in bk])
    print("PM-8 markets with a quote 24h out: %d" % len(bk))
    for lo, hi in ((0, .03), (.03, .06), (.06, .10), (.10, .20), (.40, .60), (.80, .90), (.90, .97), (.97, 1.0)):
        k = (A > lo) & (A <= hi)
        if k.sum():
            print("  YES ask %2d-%2dc: n=%5d  avg ask %.3f  YES actually won %.3f" % (100 * lo, 100 * hi, k.sum(), A[k].mean(), Y[k].mean()))
    print("PM-8 trades %d in %d events, %d series" % (len(tr), len({t['ev'] for t in tr}), len({t['ser'] for t in tr})))
    if not tr:
        return
    print("  per contract: net $%+.2f avg %+.4f, NO won %.1f%% at avg cost %.3f" % (
        sum(t["net"] for t in tr), np.mean([t["net"] for t in tr]), 100 * np.mean([t["won"] for t in tr]), np.mean([t["no"] for t in tr])))
    top = collections.Counter(t["ser"] for t in tr).most_common(8)
    print("  top series:", ", ".join("%s %d ($%+.2f)" % (s, n, sum(t["net"] for t in tr if t["ser"] == s)) for s, n in top))
    nets, keys = per_event(tr)
    report("PM-8 kalshi_longshot_no, per EVENT totals ($ per 1 contract each)", nets, keys)
    for c in (0.08, 0.12):
        n2, _ = per_event(run(c)[0]); print("  cut %dc: events %d net $%+.2f t %+.2f" % (100 * c, len(n2), sum(n2), tstat(n2)))
    n3, _ = per_event(run(band=(0.40, 0.60))[0]); print("  placebo (NO on 40-60c): events %d net $%+.2f t %+.2f" % (len(n3), sum(n3), tstat(n3)))
    d = collections.defaultdict(float)
    for t in tr:
        d[t["day"]] += t["net"]
    print("  days %d; drop best 2 days: $%+.2f -> $%+.2f" % (len(d), sum(d.values()), sum(d.values()) - sum(sorted(d.values())[-2:])))
    s2 = [t for t in tr if not t["ser"].startswith(("KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE"))]
    n4, _ = per_event(s2); print("  excluding crypto ladders: events %d net $%+.2f t %+.2f" % (len(n4), sum(n4), tstat(n4)))


if __name__ == "__main__":
    fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 30) if "fetch" in sys.argv else main()
