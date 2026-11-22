"""PM-3: Polymarket 5-min up/down streak reversal as a MAKER (pre-declared in results/sweep_log.csv).
Winners from gamma (free); every real trade from data-api v2 (free) -> a resting limit buy at L fills ONLY if a trade printed
strictly through it within the first 4 minutes: our token traded < L, or the complement traded > 1 - L (same thing on a binary).
    python run_pm_updown_maker.py fetch [days]     # cache -> data/pm_updown_mk/
    python run_pm_updown_maker.py                   # the test
"""
import collections, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import requests

from core.backtest import report, tstat

H = {"User-Agent": "Mozilla/5.0"}
OUT = "data/pm_updown_mk"
COINS = ["btc", "eth", "sol", "xrp"]
STREAK, LIMIT, CANCEL = 3, 0.49, 240
S = requests.Session(); S.headers.update(H)


def get(url, **p):
    for i in range(6):
        try:
            r = S.get(url, params=p, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(1.5 * (i + 1)); continue
            return r.json()
        except requests.RequestException:
            time.sleep(1.5 * (i + 1))
    return None


def event(coin, ws):
    f = os.path.join(OUT, "ev", f"{coin}_{ws}.json")
    if os.path.exists(f):
        return json.load(open(f))
    j = get("https://gamma-api.polymarket.com/events", slug=f"{coin}-updown-5m-{ws}")
    if not j:
        return None
    m = j[0]["markets"][0]
    px = [float(x) for x in json.loads(m["outcomePrices"])]
    outs = json.loads(m["outcomes"])
    if not m.get("closed") or 1.0 not in px:
        return None
    e = dict(ws=ws, cid=m["conditionId"], winner=outs[px.index(1.0)], tokens=dict(zip(outs, json.loads(m["clobTokenIds"]))),
             fee=(m.get("feeSchedule") or {}).get("rate", 0.05))
    json.dump(e, open(f, "w"))
    return e


def trades(e):
    """all trades in [open, open+CANCEL] -> [(ts, token, price)], cached."""
    f = os.path.join(OUT, "tr", f"{e['cid'][:20]}.json")
    if os.path.exists(f):
        return json.load(open(f))
    out, cur = [], None
    for _ in range(20):
        p = dict(condition=e["cid"], limit=1000)
        if cur:
            p["cursor"] = cur
        j = get("https://data-api.polymarket.com/v2/trades", **p)
        if not j:
            return None
        rows = j.get("data") or []
        out += [(r["timestamp"], r["token_id"], r["price"]) for r in rows]
        pg = j.get("pagination") or {}
        if not rows or not pg.get("has_more") or min(r["timestamp"] for r in rows) < e["ws"]:
            break
        cur = pg.get("next_cursor")
    out = sorted(x for x in out if e["ws"] <= x[0] <= e["ws"] + CANCEL)
    json.dump(out, open(f, "w"))
    return out


def fetch(days=14):
    for d in ("ev", "tr"):
        os.makedirs(os.path.join(OUT, d), exist_ok=True)
    end = int(time.time()) // 300 * 300 - 600; start = end - days * 86400
    with ThreadPoolExecutor(8) as ex:
        for coin in COINS:
            wins = list(range(start, end + 1, 300))
            evs = list(ex.map(lambda w: event(coin, w), wins))
            print(coin, "windows", len(wins), "resolved", sum(e is not None for e in evs), flush=True)
            # trades only where the rule fires, plus the placebo sample (every 8th non-signal window)
            need = []
            for i, e in enumerate(evs):
                if e is None:
                    continue
                prev = [x["winner"] if x else None for x in evs[max(0, i - STREAK):i]]
                sig = len(prev) == STREAK and None not in prev and len(set(prev)) == 1
                if sig or i % 8 == 0:
                    need.append(e)
            list(ex.map(trades, need))
            print(coin, "trade sets", len(need), flush=True)


def load(coin):
    d = os.path.join(OUT, "ev")
    evs = {}
    for fn in os.listdir(d):
        if fn.startswith(coin + "_"):
            e = json.load(open(os.path.join(d, fn))); evs[e["ws"]] = e
    return evs


def sim(limit=LIMIT, placebo=False, taker=False):
    res = []
    for coin in COINS:
        evs = load(coin)
        for ws in sorted(evs):
            prev = [evs.get(ws - 300 * k, {}).get("winner") for k in range(STREAK, 0, -1)]
            sig = None not in prev and len(set(prev)) == 1
            if placebo:
                if sig or (ws // 300) % 8 != 0:
                    continue
                side = "Up" if (ws // 300) % 16 else "Down"      # fixed, arbitrary side for the placebo
            else:
                if not sig:
                    continue
                side = "Down" if prev[-1] == "Up" else "Up"
            e = evs[ws]
            f = os.path.join(OUT, "tr", f"{e['cid'][:20]}.json")
            if not os.path.exists(f):
                continue
            tr = json.load(open(f)); tok = e["tokens"][side]
            win = e["winner"] == side
            if taker:
                first = next(((t, p if k == tok else 1 - p) for t, k, p in tr), None)
                if not first or not (0.05 < first[1] < 0.95):
                    continue
                c = first[1]; fee = e["fee"] * c * (1 - c)
                res.append(dict(coin=coin, ws=ws, win=win, net=(1 - c - fee) if win else -(c + fee), price=c))
                continue
            filled = any((k == tok and p < limit) or (k != tok and p > 1 - limit) for t, k, p in tr)
            if filled:
                res.append(dict(coin=coin, ws=ws, win=win, net=(1 - limit) if win else -limit, price=limit))
            else:
                res.append(dict(coin=coin, ws=ws, win=win, net=None, price=limit))
    return res


def main():
    mk = sim()
    f = [r for r in mk if r["net"] is not None]
    print("PM-3 signals %d, maker filled %d (%.0f%%)" % (len(mk), len(f), 100 * len(f) / max(1, len(mk))))
    print("  win rate when FILLED %.1f%% vs when NOT filled %.1f%% (adverse selection check), all signals %.1f%%" % (
        100 * sum(r["win"] for r in f) / max(1, len(f)), 100 * sum(r["win"] for r in mk if r["net"] is None) / max(1, len(mk) - len(f)),
        100 * sum(r["win"] for r in mk) / max(1, len(mk))))
    for c in COINS:
        v = [r["net"] for r in f if r["coin"] == c]
        if v:
            print("  %s n=%d net $%+.2f/share win %.0f%%" % (c, len(v), sum(v), 100 * sum(x > 0 for x in v) / len(v)))
    report("PM-3 pm_updown_rev3 MAKER @%.2f (net $ per share)" % LIMIT, [r["net"] for r in f], [r["ws"] for r in f])
    tk = sim(taker=True)
    print("  TAKER at first trade + fee: n=%d net $%+.2f avg %+.4f t %+.2f win %.1f%%" % (
        len(tk), sum(r["net"] for r in tk), sum(r["net"] for r in tk) / max(1, len(tk)), tstat([r["net"] for r in tk]),
        100 * sum(r["win"] for r in tk) / max(1, len(tk))))
    for L in (0.48, 0.50):
        v = [r["net"] for r in sim(L) if r["net"] is not None]
        print("  limit %.2f: n=%d net $%+.2f avg %+.4f t %+.2f" % (L, len(v), sum(v), sum(v) / max(1, len(v)), tstat(v)))
    pv = [r["net"] for r in sim(placebo=True) if r["net"] is not None]
    print("  placebo (no-streak windows, fixed side, same maker fill): n=%d net $%+.2f avg %+.4f t %+.2f" % (
        len(pv), sum(pv), sum(pv) / max(1, len(pv)), tstat(pv)))
    d = collections.defaultdict(float)
    for r in f:
        d[time.strftime("%Y-%m-%d", time.gmtime(r["ws"]))] += r["net"]
    print("  days %d; drop best 2 days: $%+.2f -> $%+.2f" % (len(d), sum(d.values()), sum(d.values()) - sum(sorted(d.values())[-2:])))


if __name__ == "__main__":
    fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 14) if "fetch" in sys.argv else main()
