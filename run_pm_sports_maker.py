"""PM-5: Polymarket game moneylines as a MAKER anchored on Pinnacle (pre-declared in results/sweep_log.csv).
Reuses PM-2's caches (data/pm_poly: matched games + Pinnacle archive); adds every real trade (data-api v2, free) per game.
A resting bid fills only if a trade prints strictly through it while the bid is live.
    python run_pm_sports_maker.py fetch
    python run_pm_sports_maker.py
"""
import collections, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np

from core.backtest import report, tstat
from run_pm_sharp_study import get, ts, snaps

OUT = "data/pm_poly"
OFF = 0.02


def cid(slug):
    f = os.path.join(OUT, "cid_" + slug + ".json")
    if os.path.exists(f):
        return json.load(open(f))
    g = get("https://gamma-api.polymarket.com/events", slug=slug)
    c = [m["conditionId"] for m in g[0]["markets"] if m["slug"] == slug][0]
    json.dump(c, open(f, "w"))
    return c


def trades(slug, t0):
    """pregame trades [(ts, token, price)] from 25h before the start to the start."""
    f = os.path.join(OUT, "tr_" + slug + ".json")
    if os.path.exists(f):
        return json.load(open(f))
    c = cid(slug); out, cur = [], None
    for _ in range(60):
        p = dict(condition=c, limit=1000)
        if cur:
            p["cursor"] = cur
        j = get("https://data-api.polymarket.com/v2/trades", **p)
        rows = (j or {}).get("data") or []
        out += [(r["timestamp"], r["token_id"], r["price"]) for r in rows if t0 - 25 * 3600 <= r["timestamp"] <= t0]
        if not rows or not j["pagination"].get("has_more") or min(r["timestamp"] for r in rows) < t0 - 25 * 3600:
            break
        cur = j["pagination"]["next_cursor"]
    out.sort(); json.dump(out, open(f, "w"))
    return out


def fetch():
    match = json.load(open(os.path.join(OUT, "match.json")))
    games = {r["k"]: r for r in snaps()}
    jobs = [(e["slug"], ts(games[k]["t"])) for k, e in match.items()]
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda j: trades(*j), jobs))
    print("trade sets", len(jobs))


def run(off=OFF):
    match = json.load(open(os.path.join(OUT, "match.json")))
    by = collections.defaultdict(list)
    for r in snaps():
        if r["k"] in match:
            by[r["k"]].append(r)
    res = []
    for k, rows in by.items():
        e = match[k]; f = os.path.join(OUT, "tr_" + e["slug"] + ".json")
        if not os.path.exists(f):
            continue
        tr = json.load(open(f)); rows.sort(key=lambda r: r["ts"])
        t0 = ts(rows[0]["t"]); stop = t0 - 1800
        pre = [r for r in rows if 1800 <= t0 - ts(r["ts"]) <= 86400]
        for side in ("home", "away"):
            tok = e["tokens"][e[side]]
            for i, r in enumerate(pre):
                p = r["ph"] if side == "home" else r["pa"]
                L = np.floor(100 * (p - off) + 1e-9) / 100
                if not (0.03 <= L <= 0.97):
                    continue
                a = ts(r["ts"]); b = min(ts(pre[i + 1]["ts"]) if i + 1 < len(pre) else stop, stop)
                hit = next((t for t, kk, px in tr if a < t <= b and ((kk == tok and px < L - 1e-9) or (kk != tok and px > 1 - L + 1e-9))), None)
                if hit:
                    win = float(e["prices"][e[side]]) > 0.5
                    res.append(dict(day=r["ts"][:10], lg=r["lg"], game=k, side=side, pin=p, L=L, win=win, net=(1 - L) if win else -L,
                                    mins=round((t0 - hit) / 60)))
                    break
    return res


def main():
    tr = run()
    print("PM-5 fills %d (of %d game-sides possible)" % (len(tr), 2 * len(json.load(open(os.path.join(OUT, "match.json"))))))
    if not tr:
        return
    print("  filled: won %.1f%% vs Pinnacle-expected %.1f%% (adverse selection = the gap), avg limit %.3f" % (
        100 * np.mean([t["win"] for t in tr]), 100 * np.mean([t["pin"] for t in tr]), np.mean([t["L"] for t in tr])))
    for lg in sorted({t["lg"] for t in tr}):
        v = [t["net"] for t in tr if t["lg"] == lg]
        print("  %s n=%d net $%+.2f avg %+.4f" % (lg, len(v), sum(v), np.mean(v)))
    report("PM-5 polymarket sports maker @ Pinnacle fair - 2c (net $ per share)", [t["net"] for t in tr], [t["day"] + t["game"] for t in tr])
    for o in (0.016, 0.024, 0.04):
        v = [t["net"] for t in run(o)]
        print("  offset %.1fc: n=%d net $%+.2f avg %+.4f t %+.2f" % (100 * o, len(v), sum(v), np.mean(v), tstat(v)))
    d = collections.defaultdict(float)
    for t in tr:
        d[t["day"]] += t["net"]
    print("  days %d; drop best 2 days: $%+.2f -> $%+.2f" % (len(d), sum(d.values()), sum(d.values()) - sum(sorted(d.values())[-2:])))


if __name__ == "__main__":
    fetch() if "fetch" in sys.argv else main()
