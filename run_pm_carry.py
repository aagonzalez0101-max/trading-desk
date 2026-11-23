"""PM-9: Polymarket 'near-certain' carry -- buy 95-99c outcomes 3 days before the SCHEDULED end (pre-declared by the 11/23 cloud run
in results/sweep_log.csv, before any data). Gamma /markets (closed) + clob prices-history, both free.
    python run_pm_carry.py fetch [days]
    python run_pm_carry.py
"""
import collections, datetime, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np

from core.backtest import report, tstat
from run_pm_sharp_study import get, ts

G = "https://gamma-api.polymarket.com"; C = "https://clob.polymarket.com"
OUT = "data/pm_carry"
LEAD, SLIP = 3 * 86400, 0.01


def iso(s):
    return ts(s.replace(" ", "T").replace("+00", "+00:00").replace("+00:00:00", "+00:00")) if s else None


def fetch(days=60):
    os.makedirs(os.path.join(OUT, "h"), exist_ok=True)
    mf = os.path.join(OUT, "markets.json")
    if not os.path.exists(mf):
        today = datetime.date.today()

        def one_day(k):
            d0 = today - datetime.timedelta(days=k + 1); d1 = d0 + datetime.timedelta(days=1)
            out, cur = [], None
            for _ in range(2000):                        # keyset paging (offset paging stops at ~3,000)
                p = dict(closed="true", end_date_min=f"{d0}T00:00:00Z", end_date_max=f"{d1}T00:00:00Z", limit=100)
                if cur:
                    p["after_cursor"] = cur
                try:
                    j = get(G + "/markets/keyset", **p) or {}
                except RuntimeError:
                    print("  gave up on part of", d0, flush=True); break
                rows = j.get("markets") or []
                for m in rows:
                    if m.get("sportsMarketType") or m.get("gameStartTime"):
                        continue                         # non-sports only (pre-declared)
                    s, e = iso(m.get("startDate")), iso(m.get("endDate"))
                    if not s or not e or e - s < LEAD + 86400:
                        continue                         # must exist before the decision day
                    try:
                        toks, outs, px = json.loads(m["clobTokenIds"]), json.loads(m["outcomes"]), [float(x) for x in json.loads(m["outcomePrices"])]
                    except Exception:
                        continue
                    if len(toks) != 2 or max(px) < 0.99:
                        continue                         # binary and actually resolved to $1/$0
                    out.append(dict(slug=m.get("slug"), ev=(m.get("events") or [{}])[0].get("slug") or m.get("slug"), start=s, end=e,
                                    closed=iso(m.get("closedTime")), toks=toks, outs=outs, win=px.index(max(px)),
                                    fee=(m.get("feeSchedule") or {}).get("rate", 0.0) or 0.0, q=m.get("question")))
                cur = j.get("next_cursor")
                if not cur or not rows:
                    break
            return out
        ms = []
        with ThreadPoolExecutor(6) as ex:
            for r in ex.map(one_day, range(days)):
                ms += r
        json.dump(ms, open(mf, "w"))
    ms = json.load(open(mf))
    ms = [m for m in ms if not (m["closed"] and m["closed"] <= m["end"] - LEAD)]     # resolved before the decision -> skip
    print("markets", len(ms), "events", len({m['ev'] for m in ms}), flush=True)

    def hist(m):
        D = m["end"] - LEAD
        for tok in m["toks"]:
            f = os.path.join(OUT, "h", tok[:30] + ".json")
            if os.path.exists(f):
                continue
            j = get(C + "/prices-history", market=tok, startTs=int(D - 86400), endTs=int(D), fidelity=60)
            json.dump([(x["t"], x["p"]) for x in (j or {}).get("history", [])], open(f, "w"))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(hist, ms))


def run(lo=0.95, hi=0.99):
    ms = json.load(open(os.path.join(OUT, "markets.json")))
    out = []
    for m in ms:
        D = m["end"] - LEAD
        if m["closed"] and m["closed"] <= D:
            continue
        for i, tok in enumerate(m["toks"]):
            f = os.path.join(OUT, "h", tok[:30] + ".json")
            if not os.path.exists(f):
                continue
            h = [x for x in json.load(open(f)) if D - 86400 <= x[0] <= D]
            if len(h) < 10:
                continue                                 # liquidity: >= 10 price points in the 24h before the decision
            p = float(h[-1][1])
            if not (lo <= p <= hi):
                continue
            cost = p + SLIP + m["fee"] * p * (1 - p)
            won = m["win"] == i
            out.append(dict(ev=m["ev"], day=datetime.datetime.utcfromtimestamp(m["end"]).date().isoformat(), D=D, p=p, cost=cost, won=won,
                            net=(1 - cost) if won else -cost, days=(m["end"] - D) / 86400, q=m["q"]))
    return out


def per_event(tr):
    h = collections.defaultdict(float); first = {}
    for t in tr:
        h[t["ev"]] += t["net"]; first[t["ev"]] = min(first.get(t["ev"], 9e18), t["D"])
    k = sorted(h, key=lambda e: first[e])
    return [h[e] for e in k], [first[e] for e in k]


def main():
    tr = run()
    print("PM-9 trades %d in %d events" % (len(tr), len({t['ev'] for t in tr})))
    if not tr:
        return
    print("  bought at avg %.3f (cost incl. slippage/fee %.3f), won %.2f%% -> break-even needs %.2f%%" % (
        np.mean([t["p"] for t in tr]), np.mean([t["cost"] for t in tr]), 100 * np.mean([t["won"] for t in tr]), 100 * np.mean([t["cost"] for t in tr])))
    print("  per $1 share: net $%+.2f avg %+.4f; losers %d (each costs ~%.2f)" % (
        sum(t["net"] for t in tr), np.mean([t["net"] for t in tr]), sum(not t["won"] for t in tr), np.mean([t["cost"] for t in tr if not t["won"]] or [0])))
    for t in [t for t in tr if not t["won"]][:8]:
        print("    LOST at %.2f: %s" % (t["p"], (t["q"] or "")[:90]))
    nets, keys = per_event(tr)
    report("PM-9 polymarket near-certain carry, per EVENT totals ($ per share each)", nets, keys)
    ann = np.mean([t["net"] / t["cost"] for t in tr]) * 365 / 3
    print("  carry: %+.2f%% per 3-day hold -> %+.0f%%/yr if repeated (cash in a T-bill ~4%%/yr)" % (100 * np.mean([t["net"] / t["cost"] for t in tr]), 100 * ann))
    for lo, hi in ((0.94, 0.99), (0.96, 0.99), (0.95, 0.985)):
        n2, _ = per_event(run(lo, hi)); print("  band %.3f-%.3f: events %d net $%+.2f t %+.2f" % (lo, hi, len(n2), sum(n2), tstat(n2)))
    n3, _ = per_event(run(0.85, 0.90)); print("  placebo 0.85-0.90: events %d net $%+.2f t %+.2f" % (len(n3), sum(n3), tstat(n3)))
    d = collections.defaultdict(float)
    for t in tr:
        d[t["day"]] += t["net"]
    print("  days %d; drop best 2 days: $%+.2f -> $%+.2f" % (len(d), sum(d.values()), sum(d.values()) - sum(sorted(d.values())[-2:])))


if __name__ == "__main__":
    fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 60) if "fetch" in sys.argv else main()
