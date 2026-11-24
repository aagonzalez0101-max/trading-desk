"""PM-9b: near-certain carry on ordinary EVENT markets only, tested on UNSEEN October data (pre-declared in results/sweep_log.csv after
PM-9's category split -- so it must prove itself out-of-sample). Cost = mid + 1.35c (measured live ask gap) + fee; voided / 50-50
resolutions are kept (payout = final outcome price).
    python run_pm_carry_b.py fetch
    python run_pm_carry_b.py
"""
import collections, datetime, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np

from core.backtest import report, tstat
from run_pm_sharp_study import get, ts
from run_pm_carry import iso, per_event, G, C, LEAD

OUT = "data/pm_carry_b"
ASKGAP = 0.0135
EXCL = re.compile(r"bitcoin|ethereum|solana|\bxrp\b|dogecoin|price of|\bgold\b|silver|\boil\b|xauusd|xagusd|netflix|spotify|billboard|box office", re.I)


def fetch():
    os.makedirs(os.path.join(OUT, "h"), exist_ok=True)
    mf = os.path.join(OUT, "markets.json")
    if not os.path.exists(mf):
        def one_day(d0):
            d1 = d0 + datetime.timedelta(days=1); out, cur = [], None
            for _ in range(2000):
                p = dict(closed="true", end_date_min=f"{d0}T00:00:00Z", end_date_max=f"{d1}T00:00:00Z", limit=100)
                if cur:
                    p["after_cursor"] = cur
                try:
                    j = get(G + "/markets/keyset", **p) or {}
                except RuntimeError:
                    print("  gave up on part of", d0, flush=True); break
                rows = j.get("markets") or []
                for m in rows:
                    q = m.get("question") or ""
                    if m.get("sportsMarketType") or m.get("gameStartTime") or EXCL.search(q):
                        continue
                    s, e = iso(m.get("startDate")), iso(m.get("endDate"))
                    if not s or not e or e - s < LEAD + 86400:
                        continue
                    try:
                        toks, px = json.loads(m["clobTokenIds"]), [float(x) for x in json.loads(m["outcomePrices"])]
                    except Exception:
                        continue
                    if len(toks) != 2 or abs(sum(px) - 1) > 0.02:
                        continue                         # keep any settled payout incl. 50-50 / voided, skip unsettled
                    out.append(dict(ev=(m.get("events") or [{}])[0].get("slug") or m.get("slug"), end=e, closed=iso(m.get("closedTime")),
                                    toks=toks, pay=px, fee=(m.get("feeSchedule") or {}).get("rate", 0.0) or 0.0, q=q))
                cur = j.get("next_cursor")
                if not cur or not rows:
                    break
            return out
        days = [datetime.date(2026, 10, 1) + datetime.timedelta(days=k) for k in range(31)]
        ms = []
        with ThreadPoolExecutor(6) as ex:
            for r in ex.map(one_day, days):
                ms += r
        json.dump(ms, open(mf, "w"))
    ms = [m for m in json.load(open(mf)) if not (m["closed"] and m["closed"] <= m["end"] - LEAD)]
    print("October event markets %d (%d events), non-50/50 %d" % (len(ms), len({m['ev'] for m in ms}), sum(max(m['pay']) > 0.99 for m in ms)), flush=True)

    def hist(m):
        D = m["end"] - LEAD
        for tok in m["toks"]:
            f = os.path.join(OUT, "h", tok[:30] + ".json")
            if os.path.exists(f):
                continue
            try:
                j = get(C + "/prices-history", market=tok, startTs=int(D - 86400), endTs=int(D), fidelity=60)
            except RuntimeError:
                continue
            json.dump([(x["t"], x["p"]) for x in (j or {}).get("history", [])], open(f, "w"))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(hist, ms))


def run(lo=0.95, hi=0.99):
    out = []
    for m in json.load(open(os.path.join(OUT, "markets.json"))):
        D = m["end"] - LEAD
        if m["closed"] and m["closed"] <= D:
            continue
        for i, tok in enumerate(m["toks"]):
            f = os.path.join(OUT, "h", tok[:30] + ".json")
            if not os.path.exists(f):
                continue
            h = [x for x in json.load(open(f)) if D - 86400 <= x[0] <= D]
            if len(h) < 10:
                continue
            p = float(h[-1][1])
            if not (lo <= p <= hi):
                continue
            cost = p + ASKGAP + m["fee"] * p * (1 - p)
            out.append(dict(ev=m["ev"], day=datetime.datetime.fromtimestamp(m["end"], datetime.timezone.utc).date().isoformat(), D=D, p=p,
                            cost=cost, pay=m["pay"][i], net=m["pay"][i] - cost, q=m["q"]))
    return out


def main():
    tr = run()
    print("PM-9b trades %d in %d events (out-of-sample October)" % (len(tr), len({t['ev'] for t in tr})))
    if not tr:
        return
    print("  avg price %.3f, cost %.3f; paid $1: %.2f%%, paid 0: %.2f%%, partial (50/50 etc): %d" % (
        np.mean([t["p"] for t in tr]), np.mean([t["cost"] for t in tr]), 100 * np.mean([t["pay"] > 0.99 for t in tr]),
        100 * np.mean([t["pay"] < 0.01 for t in tr]), sum(0.01 <= t["pay"] <= 0.99 for t in tr)))
    print("  per share: net $%+.2f avg %+.4f" % (sum(t["net"] for t in tr), np.mean([t["net"] for t in tr])))
    for t in [t for t in tr if t["pay"] < 0.99][:8]:
        print("    paid %.2f at %.2f: %s" % (t["pay"], t["p"], (t["q"] or "")[:90]))
    nets, keys = per_event(tr)
    report("PM-9b near-certain carry, EVENT markets, Oct 2026 out-of-sample (per EVENT)", nets, keys)
    for lo, hi in ((0.94, 0.99), (0.96, 0.99)):
        n2, _ = per_event(run(lo, hi)); print("  band %.2f-%.2f: events %d net $%+.2f t %+.2f" % (lo, hi, len(n2), sum(n2), tstat(n2)))
    n3, _ = per_event(run(0.85, 0.90)); print("  placebo 0.85-0.90: events %d net $%+.2f t %+.2f" % (len(n3), sum(n3), tstat(n3)))
    d = collections.defaultdict(float)
    for t in tr:
        d[t["day"]] += t["net"]
    print("  days %d; drop best 2 days: $%+.2f -> $%+.2f" % (len(d), sum(d.values()), sum(d.values()) - sum(sorted(d.values())[-2:])))


if __name__ == "__main__":
    fetch() if "fetch" in sys.argv else main()
