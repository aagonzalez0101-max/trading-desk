"""MONEY MOVES BETWEEN THE DESKS (user 11/22: "pp is a separate bankroll no matter what").
PrizePicks (betting desk) and the trading venues (Kalshi / Polymarket / Alpaca) are SEPARATE bankrolls. The only way trading
gets real money is the user withdrawing from PrizePicks and depositing to a trading venue himself. Every move is logged here
AND mirrored as a withdrawal in ../sports betting/road.json so both desks' profit math stays honest (profit = balance - start - net deposits).
    python -m core.transfers add 200 PrizePicks Kalshi "first funding"     # log a move (after the money actually lands)
    python -m core.transfers                                               # list + totals per venue
"""
import os, sys, json, datetime

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(ROOT, "results", "transfers.jsonl")
ROAD = os.path.join(os.path.dirname(ROOT), "sports betting", "road.json")
VENUES = ("PrizePicks", "Kalshi", "Polymarket", "Alpaca", "Bank")


def rows():
    return [json.loads(l) for l in open(F, encoding="utf-8") if l.strip()] if os.path.exists(F) else []


def add(amount, src, dst, note=""):
    assert src in VENUES and dst in VENUES and src != dst and amount > 0
    r = dict(date=datetime.datetime.now(CT).date().isoformat(), amount=round(float(amount), 2), src=src, dst=dst, note=note)
    os.makedirs(os.path.dirname(F), exist_ok=True)
    with open(F, "a", encoding="utf-8") as f:
        f.write(json.dumps(r) + "\n")
    if src == "PrizePicks" or dst == "PrizePicks":                     # mirror on the betting desk as a deposit/withdrawal
        try:
            rd = json.load(open(ROAD))
            amt = -r["amount"] if src == "PrizePicks" else r["amount"]
            rd.setdefault("deposits", []).append(dict(date=r["date"], amount=amt, book="PrizePicks",
                                                      note="transfer %s -> %s (%s) logged by trading desk" % (src, dst, note)))
            if rd.get("roll_now") is not None:
                rd["roll_now"] = round(float(rd["roll_now"]) + amt, 2)
            json.dump(rd, open(ROAD, "w"), indent=1)
        except Exception as e:
            print("could not mirror to road.json:", e)
    if dst in ("Kalshi", "Polymarket", "Alpaca"):                       # raise the trading guard's live bankroll
        from core import guard
        c = guard.cfg(); c["bankroll"] = round(float(c["bankroll"]) + r["amount"], 2)
        json.dump(c, open(guard.CFG, "w"), indent=1)
    print("logged:", r)


def show():
    net = {v: 0.0 for v in VENUES}
    for r in rows():
        net[r["src"]] -= r["amount"]; net[r["dst"]] += r["amount"]
        print("  %s  $%8.2f  %s -> %s  %s" % (r["date"], r["amount"], r["src"], r["dst"], r["note"]))
    print("net moved per venue:", {k: v for k, v in net.items() if v})


if __name__ == "__main__":
    if sys.argv[1:2] == ["add"]:
        add(float(sys.argv[2]), sys.argv[3], sys.argv[4], " ".join(sys.argv[5:]))
    else:
        show()
