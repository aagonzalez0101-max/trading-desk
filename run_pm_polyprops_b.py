"""PM-11b: Polymarket NFL props vs Pinnacle / FanDuel using only TRADED prices (pre-declared in results/sweep_log.csv after PM-11 was found to
be an artifact of empty-book midpoints). Reuses PM-11's market list; adds every real trade per market (data-api v2, free).
    python run_pm_polyprops_b.py fetch
    python run_pm_polyprops_b.py
"""
import collections, datetime, json, os, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np

from core.backtest import report, tstat
from run_pm_sharp_study import get
from run_pm_polyprops import sharp, per_ladder, G, PRE

OUT = "data/pm_polyprops"
EDGE, COSTADD, WIN = 0.03, 0.015, 3600


def fetch():
    ms = json.load(open(os.path.join(OUT, "markets.json")))
    cf = os.path.join(OUT, "cids.json")
    if os.path.exists(cf):
        cids = json.load(open(cf))
    else:
        cids = {}
        for e in sorted({m["ev"] for m in ms}):
            g = get(G + "/events", slug=e) or []
            for mk in (g[0]["markets"] if g else []):
                try:
                    cids[json.loads(mk["clobTokenIds"])[0]] = mk["conditionId"]
                except Exception:
                    pass
        json.dump(cids, open(cf, "w"))
    A, B = sharp("pinnacle"), sharp("fanduel")
    need = [m for m in ms if m["start"] and m["over"] in cids and ((m["stat"], m["who"], m["line"]) in A or (m["stat"], m["who"], m["line"]) in B)]
    os.makedirs(os.path.join(OUT, "tr"), exist_ok=True)
    print("markets to pull trades for:", len(need), flush=True)

    def one(m):
        f = os.path.join(OUT, "tr", m["over"][:30] + ".json")
        if os.path.exists(f):
            return
        out, cur = [], None
        for _ in range(30):
            p = dict(condition=cids[m["over"]], limit=1000)
            if cur:
                p["cursor"] = cur
            try:
                j = get("https://data-api.polymarket.com/v2/trades", **p) or {}
            except RuntimeError:
                return
            rows = j.get("data") or []
            out += [(r["timestamp"], r["price"] if r["token_id"] == m["over"] else 1 - r["price"]) for r in rows if r["timestamp"] < m["start"] - PRE]
            pg = j.get("pagination") or {}
            if not rows or not pg.get("has_more"):
                break
            cur = pg.get("next_cursor")
        json.dump(sorted(out), open(f, "w"))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, need))


def run(book, edge=EDGE, placebo=False, S=None, ms=None):
    S = S or sharp(book); ms = ms or json.load(open(os.path.join(OUT, "markets.json")))
    out = []
    for m in ms:
        key = (m["stat"], m["who"], m["line"])
        f = os.path.join(OUT, "tr", m["over"][:30] + ".json")
        if key not in S or not m["start"] or not os.path.exists(f):
            continue
        tr = json.load(open(f))
        if not tr:
            continue
        ts_ = [x[0] for x in tr]
        for t, p in S[key]:
            if t > m["start"] - PRE:
                break
            import bisect
            i = bisect.bisect_right(ts_, t) - 1
            if i < 0 or t - tr[i][0] > WIN:
                continue                                 # no real trade in the last hour -> no price
            po = float(tr[i][1]); pu = 1 - po
            co = po + COSTADD + m["fee"] * po * (1 - po); cu = pu + COSTADD + m["fee"] * pu * (1 - pu)
            side = "OVER" if p - co >= edge and 0.03 < po < 0.97 else ("UNDER" if (1 - p) - cu >= edge and 0.03 < pu < 0.97 else None)
            if not side:
                continue
            if placebo:
                side = "UNDER" if side == "OVER" else "OVER"
            cost = co if side == "OVER" else cu
            won = m["over_won"] == (side == "OVER")
            out.append(dict(lad=(m["ev"], m["who"], m["stat"]), day=datetime.datetime.fromtimestamp(t, datetime.timezone.utc).date().isoformat(),
                            t=t, side=side, p=p if side == "OVER" else 1 - p, cost=cost, won=won, net=(1 - cost) if won else -cost))
            break
    return out


def main():
    ms = json.load(open(os.path.join(OUT, "markets.json")))
    have = [m for m in ms if os.path.exists(os.path.join(OUT, "tr", m["over"][:30] + ".json"))]
    traded = [m for m in have if json.load(open(os.path.join(OUT, "tr", m["over"][:30] + ".json")))]
    print("PM-11b: markets with trade data %d; with ANY pregame trade %d (%.0f%%)" % (len(have), len(traded), 100 * len(traded) / max(1, len(have))))
    for book in ("pinnacle", "fanduel"):
        S = sharp(book)
        g = []
        for m in traded:
            key = (m["stat"], m["who"], m["line"])
            if key not in S:
                continue
            tr = json.load(open(os.path.join(OUT, "tr", m["over"][:30] + ".json")))
            for t, p in S[key]:
                if t > m["start"] - PRE:
                    break
                q = [x for x in tr if t - WIN <= x[0] <= t]
                if q:
                    g.append(p - q[-1][1])
        if g:
            g = np.array(g)
            print("  %s: traded pairs %d, sharp - last trade mean %+.3f, abs median %.3f, 5/95th %s" % (
                book, len(g), g.mean(), np.median(abs(g)), np.percentile(g, [5, 95]).round(3)))
        tr = run(book, S=S, ms=ms)
        print("\nPM-11b vs %s: trades %d in %d ladders" % (book, len(tr), len({t['lad'] for t in tr})))
        if not tr:
            continue
        print("  per share net $%+.2f avg %+.4f; won %.1f%% vs %s-expected %.1f%% at avg cost %.3f" % (
            sum(t["net"] for t in tr), np.mean([t["net"] for t in tr]), 100 * np.mean([t["won"] for t in tr]), book,
            100 * np.mean([t["p"] for t in tr]), np.mean([t["cost"] for t in tr])))
        nets, keys = per_ladder(tr)
        report("PM-11b polymarket NFL props (TRADED prices) vs %s, per LADDER (needs t >= 2.5)" % book, nets, keys)
        for e in (0.024, 0.036):
            n2, _ = per_ladder(run(book, e, S=S, ms=ms)); print("  edge >= %.1fc: ladders %d net $%+.2f t %+.2f" % (100 * e, len(n2), sum(n2), tstat(n2)))
        n3, _ = per_ladder(run(book, placebo=True, S=S, ms=ms)); print("  placebo: ladders %d net $%+.2f t %+.2f" % (len(n3), sum(n3), tstat(n3)))
        d = collections.defaultdict(float)
        for t in tr:
            d[t["day"]] += t["net"]
        print("  days %d; drop best 2 days: $%+.2f -> $%+.2f" % (len(d), sum(d.values()), sum(d.values()) - sum(sorted(d.values())[-2:])))


if __name__ == "__main__":
    fetch() if "fetch" in sys.argv else main()
