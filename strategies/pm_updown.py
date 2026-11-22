"""POLYMARKET CRYPTO 5-MIN UP/DOWN -- streak reversal (carried over from the betting desk, 11/9).
Market: slug  <coin>-updown-5m-<unix start of the 5-min window>  (btc, eth, sol, xrp, doge, bnb). Pays $1 if right.
Rule (pre-declared 11/9): after 3+ windows in a row resolved the same way, buy the OPPOSITE side at the window's open price.
Measured so far: Coinbase candles 52.7% (n=6,205); Polymarket backfill 14 days BTC 52.0% (+2.6% taker net, z +1.21, NOT sig);
one overnight 5-coin run 45% (-$14.84 per $1). Verdict 11/10: NOT money as a TAKER. Open question: maker (limit) entries pay
no fee -- that's the only version worth paper-testing. Nothing here may trade real money (see core/guard.py).

    python -m strategies.pm_updown backfill btc 3      # last 3 days of real Polymarket windows -> report (cached in data/pm_updown/)
    python -m strategies.pm_updown paper btc           # one paper pass: settle closed paper trades, open a new one if the rule fires
    python -m strategies.pm_updown loop btc            # paper pass every 5 minutes (leave a terminal open)
"""
import os, sys, json, time, datetime
import requests
from core import ledger, guard, backtest
from core.sizing import polymarket_taker_fee

H = {"User-Agent": "Mozilla/5.0"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "pm_updown")
NAME = "pm_updown_rev3"
STREAK = 3


def window_start(ts=None):
    ts = int(ts or time.time())
    return ts - ts % 300


def event(coin, ws):
    """-> dict(slug, closed, winner 'Up'/'Down'/None, tokens{Up,Down}) for the 5-min window starting at ws. Cached once closed."""
    slug = "%s-updown-5m-%d" % (coin, ws)
    fp = os.path.join(CACHE, slug + ".json")
    if os.path.exists(fp):
        return json.load(open(fp))
    try:
        r = requests.get("https://gamma-api.polymarket.com/events", params={"slug": slug}, headers=H, timeout=20).json()
    except Exception:
        return None
    if not r:
        return None
    m = r[0]["markets"][0]
    outs = json.loads(m["outcomes"]); toks = json.loads(m["clobTokenIds"]); px = [float(x) for x in json.loads(m["outcomePrices"])]
    winner = outs[px.index(1.0)] if m.get("closed") and 1.0 in px else None
    e = dict(slug=slug, ws=ws, closed=bool(m.get("closed")), winner=winner, tokens=dict(zip(outs, toks)))
    if e["closed"] and winner:
        os.makedirs(CACHE, exist_ok=True); json.dump(e, open(fp, "w"))
    return e


def open_price(token, ws):
    """first traded price at/after the window open (prices-history, 1-min fidelity)."""
    fp = os.path.join(CACHE, "px_%s_%d.json" % (token[:16], ws))
    if os.path.exists(fp):
        return json.load(open(fp))
    try:
        h = requests.get("https://clob.polymarket.com/prices-history", params={"market": token, "startTs": ws - 60, "endTs": ws + 120,
                                                                              "fidelity": 1}, headers=H, timeout=20).json().get("history", [])
    except Exception:
        return None
    pts = [x["p"] for x in h if x["t"] >= ws - 5]
    p = pts[0] if pts else None
    if p is not None:
        os.makedirs(CACHE, exist_ok=True); json.dump(p, open(fp, "w"))
    return p


def signal(results):
    """results = winners of the windows before this one, oldest first -> side to buy or None."""
    last = results[-STREAK:]
    if len(last) == STREAK and None not in last and len(set(last)) == 1:
        return "Down" if last[0] == "Up" else "Up"
    return None


def backfill(coin="btc", days=3):
    end = window_start() - 300; start = end - days * 86400
    wins = []; nets = []; keys = []; n = 0
    for ws in range(start, end + 1, 300):
        e = event(coin, ws); n += 1
        if n % 100 == 0:
            print("  ...%d windows" % n, flush=True)
        if not e or not e["closed"]:
            wins.append(None); continue
        side = signal(wins)
        if side:
            c = open_price(e["tokens"][side], ws)
            if c and 0.05 < c < 0.95:
                fee = polymarket_taker_fee(c)
                won = e["winner"] == side
                nets.append((1 - c - fee) if won else -(c + fee)); keys.append(ws)
        wins.append(e["winner"])
    print("%s %s: %d windows, %d signals" % (NAME, coin.upper(), n, len(nets)))
    if nets:
        backtest.report("%s %s -- per $1 share, TAKER fee included" % (NAME, coin.upper()), nets, keys)
        mk = [x + polymarket_taker_fee(0.5) for x in nets]          # rough maker version: no fee (assumes the limit order fills)
        print("  maker (no fee, if filled): net $%+.2f over %d" % (sum(mk), len(mk)))


def paper(coin="btc", shares=5):
    now = window_start()
    for r in ledger.open_trades(NAME):                                # settle
        e = event(coin, int(r["symbol"].rsplit("-", 1)[1]))
        if e and e["closed"] and e["winner"]:
            won = e["winner"] == r["side"]
            fee = polymarket_taker_fee(r["entry"]) * r["qty"]
            net = (r["qty"] * (1 - r["entry"]) - fee) if won else -(r["qty"] * r["entry"] + fee)
            ledger.close_trade(r["id"], exit=1.0 if won else 0.0, net=net)
            print("settled", r["symbol"], r["side"], "W" if won else "L", "%+.2f" % net)
    prev = [event(coin, now - 300 * k) for k in range(STREAK, 0, -1)]
    side = signal([p["winner"] if p and p["closed"] else None for p in prev])
    if not side:
        print("no signal at", datetime.datetime.fromtimestamp(now).strftime("%H:%M")); return
    e = event(coin, now)
    if not e:
        print("window not listed yet"); return
    if any(r["symbol"] == e["slug"] for r in ledger.open_trades(NAME)):
        return
    try:
        c = float(requests.get("https://clob.polymarket.com/price", params={"token_id": e["tokens"][side], "side": "buy"},
                               headers=H, timeout=15).json()["price"])
    except Exception as ex:
        print("price failed:", ex); return
    ok, why = guard.allow("PAPER", stake=c * shares)
    if not ok:
        print("guard:", why); return
    ledger.open_trade("PAPER", "STRATEGY", NAME, "polymarket", e["slug"], side, shares, c, c * shares, note="streak %d reversal" % STREAK)
    print("PAPER", e["slug"], side, "@ %.2f x%d" % (c, shares))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "backfill"
    coin = sys.argv[2] if len(sys.argv) > 2 else "btc"
    if cmd == "backfill":
        backfill(coin, int(sys.argv[3]) if len(sys.argv) > 3 else 3)
    elif cmd == "paper":
        paper(coin)
    elif cmd == "loop":
        while True:
            try:
                paper(coin)
            except Exception as ex:
                print("error:", ex)
            time.sleep(300 - time.time() % 300 + 20)
