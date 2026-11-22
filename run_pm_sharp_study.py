"""PM-1: Kalshi game moneylines vs Pinnacle's de-vigged line (pre-declared in results/sweep_log.csv before any data was seen).

Sharp side: the betting desk's archive ../sports betting/sides_snap.jsonl (read-only): Pinnacle moneyline snapshots with
timestamps, NFL / NBA / NHL / CFB, 10/16-10/31/2026. Kalshi side: public API, settled game markets + 1-minute candles.
Leak guards: only Pinnacle snapshots 30 min - 24 h before the start; only Kalshi quotes from the minute candle that ENDED at or
before the snapshot (and <= 5 min before it) -- Kalshi markets stay open during the game, those candles are never used.
    python run_pm_sharp_study.py fetch     # pull Kalshi markets + candles -> data/pm_sharp/ (cached)
    python run_pm_sharp_study.py           # the test
"""
import datetime, json, math, os, re, sys, time, collections
import requests

from core.backtest import report, tstat

K = "https://api.elections.kalshi.com/trade-api/v2"; H = {"User-Agent": "Mozilla/5.0"}
SNAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sports betting", "sides_snap.jsonl")
OUT = "data/pm_sharp"
SERIES = {"nfl": "KXNFLGAME", "nba": "KXNBAGAME", "nhl": "KXNHLGAME", "cfb": "KXNCAAFGAME"}
EDGE, SLIP = 0.03, 0.01


def get(url, **p):
    for i in range(5):
        try:
            r = requests.get(url, params=p, headers=H, timeout=40)
            if r.status_code == 429:
                time.sleep(2 + 2 * i); continue
            r.raise_for_status(); return r.json()
        except requests.RequestException:
            time.sleep(2 + 2 * i)
    raise RuntimeError("failed " + url)


def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def snaps():
    rows = [json.loads(l) for l in open(SNAP, encoding="utf-8") if l.strip()]
    return [r for r in rows if r["lg"] in SERIES]


def norm(s):
    s = s.lower().replace("&", " ").replace(".", "").replace("'", "")
    s = re.sub(r"\(([^)]*)\)", r" \1 ", s)
    return re.sub(r"[^a-z0-9 ]", " ", s).split()


def name_match(kname, pname):
    """Kalshi 'Miami (FL)' / 'Los Angeles C' vs Pinnacle 'Miami Hurricanes' / 'Los Angeles Clippers': every Kalshi token must
    prefix-match a Pinnacle token, in order (state abbreviations like 'fl' are allowed to miss)."""
    k, p = norm(kname), norm(pname)
    j = 0; hit = 0
    for t in k:
        while j < len(p) and not p[j].startswith(t):
            j += 1
        if j < len(p):
            hit += 1; j += 1
        elif len(t) > 2:
            return 0
    return hit


def fetch():
    os.makedirs(OUT, exist_ok=True)
    S = snaps(); lo = min(ts(r["t"]) for r in S) - 86400; hi = max(ts(r["t"]) for r in S) + 2 * 86400
    games = {}
    for r in S:
        games.setdefault(r["k"], r)
    mk_file = os.path.join(OUT, "markets.json")
    if os.path.exists(mk_file):
        markets = json.load(open(mk_file))
    else:
        markets = []
        for lg, ser in SERIES.items():
            cur = None
            while True:
                p = dict(series_ticker=ser, limit=1000, min_close_ts=int(lo), max_close_ts=int(hi))
                if cur:
                    p["cursor"] = cur
                j = get(K + "/markets", **p)
                for m in j.get("markets", []):
                    m["lg"] = lg
                    markets.append({k: m.get(k) for k in ("ticker", "event_ticker", "yes_sub_title", "no_sub_title", "result",
                                                           "occurrence_datetime", "close_time", "lg", "volume_fp")})
                cur = j.get("cursor")
                if not cur or not j.get("markets"):
                    break
            print(lg, "markets so far", len(markets))
        json.dump(markets, open(mk_file, "w"))
    # match each Pinnacle game to its two Kalshi markets
    ev = collections.defaultdict(list)
    for m in markets:
        ev[m["event_ticker"]].append(m)
    match = {}
    for k, g in games.items():
        t0 = ts(g["t"]); best = None
        for e, ms in ev.items():
            if len(ms) != 2 or ms[0]["lg"] != g["lg"] or not ms[0].get("occurrence_datetime"):
                continue
            if abs(ts(ms[0]["occurrence_datetime"]) - t0) > 8 * 3600:
                continue
            for a, b in ((ms[0], ms[1]), (ms[1], ms[0])):
                sc = name_match(a["yes_sub_title"], g["home"]) and name_match(b["yes_sub_title"], g["away"])
                if sc and (best is None or sc > best[0]):
                    best = (sc, a, b)
        if best:
            match[k] = {"home": best[1], "away": best[2]}
    print("Pinnacle games %d, matched to Kalshi %d" % (len(games), len(match)))
    json.dump(match, open(os.path.join(OUT, "match.json"), "w"))
    for i, (k, mm) in enumerate(match.items()):
        t0 = ts(games[k]["t"])
        for side, m in mm.items():
            f = os.path.join(OUT, m["ticker"] + ".json")
            if os.path.exists(f):
                continue
            j = get(f"{K}/series/{SERIES[m['lg']]}/markets/{m['ticker']}/candlesticks", start_ts=int(t0 - 25 * 3600),
                    end_ts=int(t0), period_interval=1)
            c = [(x["end_period_ts"], (x.get("yes_ask") or {}).get("close_dollars"), (x.get("yes_bid") or {}).get("close_dollars"))
                 for x in j.get("candlesticks", [])]
            json.dump(c, open(f, "w")); time.sleep(0.12)
        if i % 50 == 0:
            print(" candles", i, "/", len(match))


def fee(a):
    return 0.07 * a * (1 - a)


def run(edge=EDGE, placebo=False, verbose=True):
    S = snaps(); match = json.load(open(os.path.join(OUT, "match.json")))
    cand = {}
    for m in (x for mm in match.values() for x in mm.values()):
        f = os.path.join(OUT, m["ticker"] + ".json")
        cand[m["ticker"]] = json.load(open(f)) if os.path.exists(f) else []
    S.sort(key=lambda r: r["ts"])
    taken = set(); trades = []
    for r in S:
        if r["k"] not in match:
            continue
        t0, t1 = ts(r["t"]), ts(r["ts"])
        if not (1800 <= t0 - t1 <= 86400):
            continue
        for side, p in (("home", r["ph"]), ("away", r["pa"])):
            m = match[r["k"]][side]
            if (r["k"], side) in taken:
                continue
            c = [x for x in cand[m["ticker"]] if x[0] <= t1 and x[0] >= t1 - 300 and x[1] is not None]
            if not c:
                continue
            a = float(c[-1][1])
            if not (0.02 <= a <= 0.98):
                continue
            e = p - a - fee(a) - SLIP
            if e < edge:
                continue
            taken.add((r["k"], side))
            buy = m
            if placebo:                          # same moment, the OTHER team's price
                buy = match[r["k"]]["away" if side == "home" else "home"]
                c2 = [x for x in cand[buy["ticker"]] if t1 - 300 <= x[0] <= t1 and x[1] is not None]
                if not c2:
                    continue
                a = float(c2[-1][1])
            win = buy["result"] == "yes"
            net = (1 - a if win else -a) - fee(a) - SLIP
            trades.append(dict(day=r["ts"][:10], lg=r["lg"], game=r["k"], team=buy["yes_sub_title"], pin=p, ask=a, edge=e,
                               win=win, net=net, mins=round((t0 - t1) / 60)))
    if verbose:
        by = collections.defaultdict(list)
        for t in trades:
            by[t["lg"]].append(t["net"])
        for lg, v in by.items():
            print("  %-4s n=%3d net $%+.2f per $1-contract avg %+.3f win %.0f%%" % (lg, len(v), sum(v), sum(v) / len(v),
                                                                                     100 * sum(x > 0 for x in v) / len(v)))
    return trades


def main():
    tr = run()
    print("PM-1 Kalshi vs Pinnacle, edge >= 3c after fee + 1c slippage")
    if not tr:
        print("no trades"); return
    ok = report("PM-1 kalshi_vs_pinnacle_ml (net $ per 1 contract)", [t["net"] for t in tr], [t["day"] + t["game"] for t in tr])
    print("  avg Pinnacle p %.3f, avg ask %.3f, avg claimed edge %.3f, actual win %.1f%% vs Pinnacle-expected %.1f%%" % (
        sum(t["pin"] for t in tr) / len(tr), sum(t["ask"] for t in tr) / len(tr), sum(t["edge"] for t in tr) / len(tr),
        100 * sum(t["win"] for t in tr) / len(tr), 100 * sum(t["pin"] for t in tr) / len(tr)))
    for e in (0.024, 0.036, 0.05):
        v = [t["net"] for t in run(e, verbose=False)]
        print("  edge >= %.1fc: n=%d net $%+.2f avg %+.3f t %+.2f" % (100 * e, len(v), sum(v), sum(v) / max(1, len(v)), tstat(v)))
    pv = [t["net"] for t in run(placebo=True, verbose=False)]
    print("  placebo (other team, same moment): n=%d net $%+.2f t %+.2f" % (len(pv), sum(pv), tstat(pv)))
    d = collections.defaultdict(float)
    for t in tr:
        d[t["day"]] += t["net"]
    best2 = sorted(d.values())[-2:]
    print("  drop best 2 days: $%+.2f -> $%+.2f" % (sum(d.values()), sum(d.values()) - sum(best2)))
    json.dump(tr, open("results/pm_sharp_trades.json", "w"), indent=0)
    return ok


if __name__ == "__main__":
    fetch() if "fetch" in sys.argv else main()
