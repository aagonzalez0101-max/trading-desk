"""THE LEDGER -- every trade logged AT ENTRY (lesson from the betting desk: trades analysed first went missing).
One JSONL file, one row per trade: results/trades.jsonl
    kind:     PAPER | LIVE                      (LIVE = real money)
    tag:      STRATEGY | MANUAL | TEST          (only STRATEGY counts toward a strategy's record)
    strategy, venue, symbol, side, qty, entry, stake ($ at risk), ts_open
    exit, net ($), ts_close, result (W/L/FLAT), note
    from core import ledger
    tid = ledger.open_trade("PAPER", "STRATEGY", "pm_updown_rev", "polymarket", "btc-updown-5m-1763740800", "UP", 5, 0.49, 2.45)
    ledger.close_trade(tid, exit=1.0, net=2.55)
    python -m core.ledger            # summary by strategy, PAPER vs LIVE
"""
import os, sys, json, uuid, datetime, collections, math

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(ROOT, "results", "trades.jsonl")


def _rows():
    if not os.path.exists(F):
        return []
    return [json.loads(l) for l in open(F, encoding="utf-8") if l.strip()]


def _write(rows):
    os.makedirs(os.path.dirname(F), exist_ok=True)
    with open(F, "w", encoding="utf-8") as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))


def open_trade(kind, tag, strategy, venue, symbol, side, qty, entry, stake, note=""):
    assert kind in ("PAPER", "LIVE") and tag in ("STRATEGY", "MANUAL", "TEST")
    tid = uuid.uuid4().hex[:10]
    r = dict(id=tid, kind=kind, tag=tag, strategy=strategy, venue=venue, symbol=symbol, side=side, qty=qty, entry=entry,
             stake=round(float(stake), 4), ts_open=datetime.datetime.now(CT).isoformat(timespec="seconds"),
             exit=None, net=None, ts_close=None, result=None, note=note)
    with open(F, "a", encoding="utf-8") as f:
        f.write(json.dumps(r) + "\n")
    return tid


def close_trade(tid, exit, net, note=None):
    rows = _rows()
    for r in rows:
        if r["id"] == tid:
            r.update(exit=exit, net=round(float(net), 4), ts_close=datetime.datetime.now(CT).isoformat(timespec="seconds"),
                     result="W" if net > 0 else ("L" if net < 0 else "FLAT"))
            if note:
                r["note"] = (r.get("note") or "") + " | " + note
    _write(rows)


def open_trades(strategy=None):
    return [r for r in _rows() if r["net"] is None and (strategy is None or r["strategy"] == strategy)]


def realized(kind=None, since=None):
    return sum(r["net"] for r in _rows() if r["net"] is not None and (kind is None or r["kind"] == kind)
               and (since is None or (r["ts_close"] or "") >= since))


def summary():
    S = collections.defaultdict(list)
    for r in _rows():
        if r["net"] is not None and r["tag"] == "STRATEGY":
            S[(r["kind"], r["strategy"])].append(r["net"])
    print("STRATEGY trades only (PAPER vs LIVE):")
    for (k, s), v in sorted(S.items()):
        n = len(v); m = sum(v) / n
        sd = (sum((x - m) ** 2 for x in v) / (n - 1)) ** .5 if n > 1 else 0
        t = m / (sd / n ** .5) if sd else 0
        print("  %-5s %-22s n=%4d  net $%+8.2f  avg $%+.3f  win %.0f%%  t %+.1f" % (k, s, n, sum(v), m, 100 * sum(x > 0 for x in v) / n, t))
    print("open trades:", len(open_trades()))


if __name__ == "__main__":
    summary()
