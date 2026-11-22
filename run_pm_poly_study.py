"""PM-2: Polymarket game moneylines vs Pinnacle's de-vigged line (pre-declared in results/sweep_log.csv before any data was seen).
Same sharp archive, snapshots and leak guards as run_pm_sharp_study.py (PM-1, Kalshi). Polymarket: gamma events (free) + clob
prices-history at 1-minute fidelity (free). That history is a mid/last price, not the ask, so cost = price + 1c + taker fee.
    python run_pm_poly_study.py fetch
    python run_pm_poly_study.py
"""
import collections, json, os, sys, time

from core.backtest import report, tstat
from run_pm_sharp_study import get, ts, snaps, name_match

G = "https://gamma-api.polymarket.com"; C = "https://clob.polymarket.com"
OUT = "data/pm_poly"
TAGS = {"nfl": "nfl", "nba": "nba", "nhl": "nhl", "cfb": "cfb"}
EDGE, SLIP = 0.03, 0.01


def fetch():
    os.makedirs(OUT, exist_ok=True)
    S = snaps(); games = {}
    for r in S:
        games.setdefault(r["k"], r)
    ev_file = os.path.join(OUT, "events.json")
    if os.path.exists(ev_file):
        evs = json.load(open(ev_file))
    else:
        evs = []
        for lg, tag in TAGS.items():
            off = 0
            while True:
                j = get(G + "/events", tag_slug=tag, closed="true", limit=100, offset=off,
                        start_date_min="2026-10-10", end_date_max="2026-11-05")
                for e in j:
                    for m in e.get("markets", []):
                        if m.get("sportsMarketType") == "moneyline" and m.get("slug") == e.get("slug"):
                            evs.append(dict(lg=lg, slug=e["slug"], start=m.get("gameStartTime"), outcomes=json.loads(m["outcomes"]),
                                            prices=json.loads(m["outcomePrices"]), tokens=json.loads(m["clobTokenIds"]),
                                            fee=(m.get("feeSchedule") or {}).get("rate", 0.0)))
                if len(j) < 100:
                    break
                off += 100
            print(lg, "moneyline markets so far", len(evs))
        json.dump(evs, open(ev_file, "w"))
    match = {}
    for k, g in games.items():
        t0 = ts(g["t"])
        for e in evs:
            if e["lg"] != g["lg"] or not e["start"] or len(e["outcomes"]) != 2:
                continue
            if abs(ts(e["start"].replace(" ", "T").replace("+00", "+00:00")) - t0) > 8 * 3600:
                continue
            o = e["outcomes"]
            for hi, ai in ((0, 1), (1, 0)):
                if name_match(o[hi], g["home"]) and name_match(o[ai], g["away"]):
                    match[k] = dict(e, home=hi, away=ai)
    print("Pinnacle games %d, matched to Polymarket %d" % (len(games), len(match)))
    json.dump(match, open(os.path.join(OUT, "match.json"), "w"))
    for i, (k, e) in enumerate(match.items()):
        t0 = ts(games[k]["t"])
        for tok in e["tokens"]:
            f = os.path.join(OUT, tok[:24] + ".json")
            if os.path.exists(f):
                continue
            j = get(C + "/prices-history", market=tok, startTs=int(t0 - 25 * 3600), endTs=int(t0), fidelity=1)
            json.dump([(x["t"], x["p"]) for x in j.get("history", [])], open(f, "w")); time.sleep(0.1)
        if i % 50 == 0:
            print(" history", i, "/", len(match))


def run(edge=EDGE, placebo=False, verbose=True):
    S = sorted(snaps(), key=lambda r: r["ts"]); match = json.load(open(os.path.join(OUT, "match.json")))
    hist = {}
    taken = set(); trades = []; seen = 0
    for r in S:
        e = match.get(r["k"])
        if not e:
            continue
        t0, t1 = ts(r["t"]), ts(r["ts"])
        if not (1800 <= t0 - t1 <= 86400):
            continue
        for side, p in (("home", r["ph"]), ("away", r["pa"])):
            if (r["k"], side) in taken:
                continue
            idx = e[side]
            if placebo:
                idx = 1 - idx
            tok = e["tokens"][idx]
            if tok not in hist:
                f = os.path.join(OUT, tok[:24] + ".json")
                hist[tok] = json.load(open(f)) if os.path.exists(f) else []
            h = [x for x in hist[tok] if t1 - 300 <= x[0] <= t1]
            if not h:
                continue
            # decide on the REAL side's price; placebo buys the other team at its own price at the same moment
            real_tok = e["tokens"][e[side]]
            if real_tok not in hist:
                f = os.path.join(OUT, real_tok[:24] + ".json"); hist[real_tok] = json.load(open(f)) if os.path.exists(f) else []
            hr = [x for x in hist[real_tok] if t1 - 300 <= x[0] <= t1]
            if not hr:
                continue
            a_real = float(hr[-1][1]); seen += 1
            if not (0.02 <= a_real <= 0.98):
                continue
            cost_real = a_real + SLIP + e["fee"] * a_real * (1 - a_real)
            ed = p - cost_real
            if ed < edge:
                continue
            taken.add((r["k"], side))
            a = float(h[-1][1]); cost = a + SLIP + e["fee"] * a * (1 - a)
            win = float(e["prices"][idx]) > 0.5
            trades.append(dict(day=r["ts"][:10], lg=r["lg"], game=r["k"], team=e["outcomes"][idx], pin=p, price=a, edge=ed,
                               win=win, net=(1 if win else 0) - cost, mins=round((t0 - t1) / 60)))
    if verbose:
        print("  snapshot-sides with a fresh Polymarket price:", seen)
        by = collections.defaultdict(list)
        for t in trades:
            by[t["lg"]].append(t["net"])
        for lg, v in by.items():
            print("  %-4s n=%3d net $%+.2f per $1 share, avg %+.3f, win %.0f%%" % (lg, len(v), sum(v), sum(v) / len(v),
                                                                                100 * sum(t > 0 for t in v) / len(v)))
    return trades


def gaps():
    """distribution of Pinnacle fair - Polymarket price, every fresh pregame pair (the tell: is there ever room?)"""
    import numpy as np
    S = snaps(); match = json.load(open(os.path.join(OUT, "match.json"))); g = []; hist = {}
    for r in S:
        e = match.get(r["k"])
        if not e:
            continue
        t0, t1 = ts(r["t"]), ts(r["ts"])
        if not (1800 <= t0 - t1 <= 86400):
            continue
        for side, p in (("home", r["ph"]), ("away", r["pa"])):
            tok = e["tokens"][e[side]]
            if tok not in hist:
                f = os.path.join(OUT, tok[:24] + ".json"); hist[tok] = json.load(open(f)) if os.path.exists(f) else []
            h = [x for x in hist[tok] if t1 - 300 <= x[0] <= t1]
            if h and 0.02 <= h[-1][1] <= 0.98:
                a = h[-1][1]; g.append((p - a, p - a - SLIP - e["fee"] * a * (1 - a)))
    if not g:
        return
    raw, net = np.array(g).T
    print("  pairs %d | raw gap Pinnacle - Polymarket: mean %+.3f, 5/50/95/99th %s | after cost >=0: %.1f%%, >=3c: %.2f%%" % (
        len(g), raw.mean(), np.percentile(raw, [5, 50, 95, 99]).round(3), 100 * (net >= 0).mean(), 100 * (net >= .03).mean()))


def main():
    gaps()
    tr = run()
    if not tr:
        print("no trades"); return
    report("PM-2 polymarket_vs_pinnacle_ml (net $ per $1 share)", [t["net"] for t in tr], [t["day"] + t["game"] for t in tr])
    print("  avg Pinnacle p %.3f, avg price %.3f, claimed edge %.3f, won %.1f%% vs Pinnacle-expected %.1f%%" % (
        *(sum(t[k] for t in tr) / len(tr) for k in ("pin", "price", "edge")), 100 * sum(t["win"] for t in tr) / len(tr),
        100 * sum(t["pin"] for t in tr) / len(tr)))
    for e in (0.024, 0.036, 0.05):
        v = [t["net"] for t in run(e, verbose=False)]
        print("  edge >= %.1fc: n=%d net $%+.2f avg %+.3f t %+.2f" % (100 * e, len(v), sum(v), sum(v) / max(1, len(v)), tstat(v)))
    pv = [t["net"] for t in run(placebo=True, verbose=False)]
    print("  placebo (other team, same moment): n=%d net $%+.2f t %+.2f" % (len(pv), sum(pv), tstat(pv)))
    d = collections.defaultdict(float)
    for t in tr:
        d[t["day"]] += t["net"]
    print("  drop best 2 days: $%+.2f -> $%+.2f" % (sum(d.values()), sum(d.values()) - sum(sorted(d.values())[-2:])))
    json.dump(tr, open("results/pm_poly_trades.json", "w"), indent=0)


if __name__ == "__main__":
    fetch() if "fetch" in sys.argv else main()
