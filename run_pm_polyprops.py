"""PM-11: Polymarket NFL player props vs Pinnacle (A) and FanDuel (B) prop lines (pre-declared in results/sweep_log.csv).
    python run_pm_polyprops.py fetch
    python run_pm_polyprops.py
"""
import collections, datetime, json, os, re, sqlite3, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np

from core.backtest import report, tstat
from run_pm_sharp_study import get, ts
from run_pm_props import norm, DB

G = "https://gamma-api.polymarket.com"; C = "https://clob.polymarket.com"
OUT = "data/pm_polyprops"
STAT = {"passing_yards": "passing yards", "rushing_yards": "rushing yards", "receiving_yards": "receiving yards", "receptions": "receptions"}
EDGE, SLIP, PRE = 0.03, 0.01, 900


def iso(s):
    return ts(s.replace(" ", "T").replace("+00", "+00:00").replace("+00:00:00", "+00:00")) if s else None


def sharp(book):
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    out = collections.defaultdict(list)
    for pl, st, ln, p, t in c.execute("select player, stat, line, p_over, ts from sharp where book=? and sport='NFL' and ts >= '2026-10-09'", (book,)):
        out[(st, norm(pl), float(ln))].append((ts(t), float(p)))
    for v in out.values():
        v.sort()
    return out


def fetch():
    os.makedirs(os.path.join(OUT, "h"), exist_ok=True)
    mf = os.path.join(OUT, "markets.json")
    if not os.path.exists(mf):
        ms, off = [], 0
        while off < 3000:
            evs = get(G + "/events", tag_slug="nfl", closed="true", limit=100, offset=off, end_date_min="2026-10-09T00:00:00Z",
                      end_date_max="2026-11-24T00:00:00Z")
            if not evs:
                break
            for e in evs:
                if "player-props" not in e.get("slug", ""):
                    continue
                for m in e.get("markets", []):
                    st = STAT.get(m.get("sportsMarketType"))
                    q = m.get("question") or ""
                    if not st or ":" not in q or m.get("line") is None:
                        continue
                    try:
                        px = [float(x) for x in json.loads(m["outcomePrices"])]
                        toks = json.loads(m["clobTokenIds"]); outs = json.loads(m["outcomes"])
                    except Exception:
                        continue
                    if max(px) < 0.99 or outs[:2] != ["Over", "Under"]:
                        continue
                    ms.append(dict(ev=e["slug"], who=norm(q.split(":")[0]), stat=st, line=float(m["line"]), start=iso(m.get("gameStartTime")),
                                   over=toks[0], under=toks[1], over_won=px[0] > 0.5, fee=(m.get("feeSchedule") or {}).get("rate", 0.05)))
            if len(evs) < 100:
                break
            off += 100
        json.dump(ms, open(mf, "w"))
    ms = json.load(open(mf)); A, B = sharp("pinnacle"), sharp("fanduel")
    need = [m for m in ms if m["start"] and ((m["stat"], m["who"], m["line"]) in A or (m["stat"], m["who"], m["line"]) in B)]
    print("polymarket NFL prop markets %d in %d games; exact line in Pinnacle or FanDuel: %d" % (len(ms), len({m['ev'] for m in ms}), len(need)), flush=True)

    def hist(m):
        for tok in (m["over"], m["under"]):
            f = os.path.join(OUT, "h", tok[:30] + ".json")
            if os.path.exists(f):
                continue
            try:
                j = get(C + "/prices-history", market=tok, startTs=int(m["start"] - 26 * 3600), endTs=int(m["start"] - PRE), fidelity=1)
            except RuntimeError:
                continue
            json.dump([(x["t"], x["p"]) for x in (j or {}).get("history", [])], open(f, "w"))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(hist, need))


def run(book, edge=EDGE, placebo=False, S=None, ms=None):
    S = S or sharp(book); ms = ms or json.load(open(os.path.join(OUT, "markets.json")))
    out = []
    for m in ms:
        key = (m["stat"], m["who"], m["line"])
        if key not in S or not m["start"]:
            continue
        fo, fu = (os.path.join(OUT, "h", t[:30] + ".json") for t in (m["over"], m["under"]))
        if not (os.path.exists(fo) and os.path.exists(fu)):
            continue
        ho, hu = json.load(open(fo)), json.load(open(fu))
        for t, p in S[key]:
            if t > m["start"] - PRE:
                break
            qo = [x for x in ho if t - 300 <= x[0] <= t]; qu = [x for x in hu if t - 300 <= x[0] <= t]
            if not qo or not qu:
                continue
            po, pu = float(qo[-1][1]), float(qu[-1][1])
            co = po + SLIP + m["fee"] * po * (1 - po); cu = pu + SLIP + m["fee"] * pu * (1 - pu)
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


def per_ladder(tr):
    h = collections.defaultdict(float); first = {}
    for t in tr:
        h[t["lad"]] += t["net"]; first[t["lad"]] = min(first.get(t["lad"], 9e18), t["t"])
    k = sorted(h, key=lambda e: first[e])
    return [h[e] for e in k], [first[e] for e in k]


def gaps(book, S, ms):
    g = []
    for m in ms:
        key = (m["stat"], m["who"], m["line"])
        fo = os.path.join(OUT, "h", m["over"][:30] + ".json")
        if key not in S or not m["start"] or not os.path.exists(fo):
            continue
        ho = json.load(open(fo))
        for t, p in S[key]:
            if t > m["start"] - PRE:
                break
            q = [x for x in ho if t - 300 <= x[0] <= t]
            if q and 0.03 < q[-1][1] < 0.97:
                g.append(p - q[-1][1])
    if g:
        g = np.array(g)
        print("  %s: pregame pairs %d, sharp - Polymarket(over) mean %+.3f, abs median %.3f, 5/95th %s" % (
            book, len(g), g.mean(), np.median(abs(g)), np.percentile(g, [5, 95]).round(3)))


def main():
    ms = json.load(open(os.path.join(OUT, "markets.json")))
    for book in ("pinnacle", "fanduel"):
        S = sharp(book); gaps(book, S, ms)
        tr = run(book, S=S, ms=ms)
        print("\nPM-11 vs %s: trades %d in %d ladders" % (book, len(tr), len({t['lad'] for t in tr})))
        if not tr:
            continue
        print("  per share net $%+.2f avg %+.4f; won %.1f%% vs %s-expected %.1f%% at avg cost %.3f" % (
            sum(t["net"] for t in tr), np.mean([t["net"] for t in tr]), 100 * np.mean([t["won"] for t in tr]), book,
            100 * np.mean([t["p"] for t in tr]), np.mean([t["cost"] for t in tr])))
        nets, keys = per_ladder(tr)
        report("PM-11 polymarket NFL props vs %s, per LADDER (needs t >= 2.5)" % book, nets, keys)
        for e in (0.024, 0.036):
            n2, _ = per_ladder(run(book, e, S=S, ms=ms)); print("  edge >= %.1fc: ladders %d net $%+.2f t %+.2f" % (100 * e, len(n2), sum(n2), tstat(n2)))
        n3, _ = per_ladder(run(book, placebo=True, S=S, ms=ms)); print("  placebo (other side): ladders %d net $%+.2f t %+.2f" % (len(n3), sum(n3), tstat(n3)))
        d = collections.defaultdict(float)
        for t in tr:
            d[t["day"]] += t["net"]
        print("  days %d; drop best 2 days: $%+.2f -> $%+.2f" % (len(d), sum(d.values()), sum(d.values()) - sum(sorted(d.values())[-2:])))


if __name__ == "__main__":
    fetch() if "fetch" in sys.argv else main()
