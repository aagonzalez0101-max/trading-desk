"""PM-10: Kalshi player-prop ladders vs Pinnacle's de-vigged prop lines (pre-declared in results/sweep_log.csv before any Kalshi price).
Sharp side: ../sports betting/lines.db table `sharp` (read-only; hourly Pinnacle prop snapshots since 10/9). Kalshi: public API.
    python run_pm_props.py fetch
    python run_pm_props.py
"""
import collections, datetime, json, os, re, sqlite3, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np

from core.backtest import report, tstat
from run_pm_sharp_study import get, ts

K = "https://api.elections.kalshi.com/trade-api/v2"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sports betting", "lines.db")
OUT = "data/pm_props"
SER = {"KXNBAPTS": ("NBA", "points"), "KXNBAREB": ("NBA", "rebounds"), "KXNBAAST": ("NBA", "assists"), "KXNBA3PT": ("NBA", "threes made"),
       "KXNHLPTS": ("NHL", "points"), "KXNHLAST": ("NHL", "assists"), "KXNHLGOAL": ("NHL", "goals"),
       "KXNFLPASSYDS": ("NFL", "passing yards"), "KXNFLRSHYDS": ("NFL", "rushing yards"), "KXNFLRECYDS": ("NFL", "receiving yards"),
       "KXNFLREC": ("NFL", "receptions")}
EDGE, SLIP, PRE = 0.03, 0.01, 3 * 3600 + 900
LO = "2026-10-09"; HI = "2026-11-23"


def norm(name):
    s = name.lower().replace("'", "").replace(".", "")
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def sharp():
    """{(sport, stat, player, line): [(ts, p_over), ...]} Pinnacle only."""
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    out = collections.defaultdict(list)
    for sp, pl, st, ln, p, t in c.execute("select sport, player, stat, line, p_over, ts from sharp where book='pinnacle' and ts >= ?", (LO,)):
        out[(sp, st, norm(pl), float(ln))].append((ts(t), float(p)))
    for v in out.values():
        v.sort()
    return out


def fetch():
    os.makedirs(os.path.join(OUT, "c"), exist_ok=True)
    mf = os.path.join(OUT, "markets.json")
    if not os.path.exists(mf):
        lo = int(ts(LO + "T00:00:00+00:00")); hi = int(ts(HI + "T12:00:00+00:00"))

        def one(ser):
            out, cur = [], None
            for _ in range(200):
                p = dict(series_ticker=ser, status="settled", limit=1000, min_close_ts=lo, max_close_ts=hi)
                if cur:
                    p["cursor"] = cur
                try:
                    j = get(K + "/markets", **p) or {}
                except RuntimeError:
                    break
                for m in j.get("markets", []):
                    if m.get("result") in ("yes", "no") and m.get("occurrence_datetime") and ":" in (m.get("yes_sub_title") or ""):
                        out.append(dict(tk=m["ticker"], ev=m["event_ticker"], ser=ser, who=norm(m["yes_sub_title"].split(":")[0]),
                                        line=float(m["floor_strike"]), occ=m["occurrence_datetime"], res=m["result"]))
                cur = j.get("cursor")
                if not cur or not j.get("markets"):
                    break
            return out
        ms = []
        with ThreadPoolExecutor(6) as ex:
            for r in ex.map(one, SER):
                ms += r
        json.dump(ms, open(mf, "w"))
    ms = json.load(open(mf)); S = sharp()
    hit = [m for m in ms if (SER[m["ser"]][0], SER[m["ser"]][1], m["who"], m["line"]) in S]
    print("kalshi prop markets %d, with an exact Pinnacle line %d (%d events)" % (len(ms), len(hit), len({m['ev'] for m in hit})), flush=True)

    def candles(m):
        f = os.path.join(OUT, "c", m["tk"] + ".json")
        if os.path.exists(f):
            return
        st = ts(m["occ"]) - 3 * 3600
        try:
            j = get(f"{K}/series/{m['ser']}/markets/{m['tk']}/candlesticks", start_ts=int(st - 26 * 3600), end_ts=int(st - 900), period_interval=1)
        except RuntimeError:
            return
        json.dump([(x["end_period_ts"], (x.get("yes_ask") or {}).get("close_dollars"), (x.get("yes_bid") or {}).get("close_dollars"))
                   for x in (j or {}).get("candlesticks", [])], open(f, "w"))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(candles, hit))


def fee(c):
    return 0.07 * c * (1 - c)


def run(edge=EDGE, placebo=False, S=None, ms=None):
    S = S or sharp(); ms = ms or json.load(open(os.path.join(OUT, "markets.json")))
    out = []
    for m in ms:
        key = (SER[m["ser"]][0], SER[m["ser"]][1], m["who"], m["line"])
        f = os.path.join(OUT, "c", m["tk"] + ".json")
        if key not in S or not os.path.exists(f):
            continue
        c = [x for x in json.load(open(f)) if x[1] is not None and x[2] is not None]
        if not c:
            continue
        cut = ts(m["occ"]) - PRE
        for t, p in S[key]:
            if t > cut:
                break
            q = [x for x in c if t - 300 <= x[0] <= t]
            if not q:
                continue
            ask, bid = float(q[-1][1]), float(q[-1][2]); na = 1 - bid
            ey = p - ask - fee(ask) - SLIP; en = (1 - p) - na - fee(na) - SLIP
            side = "YES" if ey >= edge and 0.02 <= ask <= 0.98 else ("NO" if en >= edge and 0.02 <= na <= 0.98 else None)
            if not side:
                continue
            if placebo:
                side = "NO" if side == "YES" else "YES"
            cost = ask if side == "YES" else na
            won = (m["res"] == "yes") == (side == "YES")
            out.append(dict(ev=m["ev"], ser=m["ser"], day=datetime.datetime.utcfromtimestamp(t).date().isoformat(), t=t, side=side,
                            p=p if side == "YES" else 1 - p, cost=cost, won=won, net=(1 - cost if won else -cost) - fee(cost) - SLIP,
                            mins=round((ts(m["occ"]) - 3 * 3600 - t) / 60)))
            break
    return out


def per_event(tr):
    h = collections.defaultdict(float); first = {}
    for t in tr:
        h[t["ev"]] += t["net"]; first[t["ev"]] = min(first.get(t["ev"], 9e18), t["t"])
    k = sorted(h, key=lambda e: first[e])
    return [h[e] for e in k], [first[e] for e in k]


def main():
    S = sharp(); ms = json.load(open(os.path.join(OUT, "markets.json")))
    tr = run(S=S, ms=ms)
    print("PM-10 trades %d in %d events" % (len(tr), len({t['ev'] for t in tr})))
    if not tr:
        return
    print("  per contract: net $%+.2f avg %+.4f; won %.1f%% vs Pinnacle-expected %.1f%% at avg cost %.3f; median %d min before start" % (
        sum(t["net"] for t in tr), np.mean([t["net"] for t in tr]), 100 * np.mean([t["won"] for t in tr]), 100 * np.mean([t["p"] for t in tr]),
        np.mean([t["cost"] for t in tr]), np.median([t["mins"] for t in tr])))
    for s in SER:
        v = [t["net"] for t in tr if t["ser"] == s]
        if v:
            print("  %-13s n=%4d net $%+7.2f avg %+.4f win %.0f%%" % (s, len(v), sum(v), np.mean(v), 100 * np.mean([x > 0 for x in v])))
    for sd in ("YES", "NO"):
        v = [t["net"] for t in tr if t["side"] == sd]
        print("  %s n=%d net $%+.2f avg %+.4f" % (sd, len(v), sum(v), np.mean(v) if v else 0))
    nets, keys = per_event(tr)
    report("PM-10 kalshi props vs Pinnacle, per EVENT totals ($ per 1 contract each)", nets, keys)
    for e in (0.024, 0.036, 0.05):
        n2, _ = per_event(run(e, S=S, ms=ms)); print("  edge >= %.1fc: events %d net $%+.2f t %+.2f" % (100 * e, len(n2), sum(n2), tstat(n2)))
    n3, _ = per_event(run(placebo=True, S=S, ms=ms)); print("  placebo (other side): events %d net $%+.2f t %+.2f" % (len(n3), sum(n3), tstat(n3)))
    d = collections.defaultdict(float)
    for t in tr:
        d[t["day"]] += t["net"]
    print("  days %d; drop best 2 days: $%+.2f -> $%+.2f" % (len(d), sum(d.values()), sum(d.values()) - sum(sorted(d.values())[-2:])))
    json.dump(tr, open("results/pm_props_trades.json", "w"), indent=0)


if __name__ == "__main__":
    fetch() if "fetch" in sys.argv else main()
