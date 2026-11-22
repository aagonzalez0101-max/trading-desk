"""COMBINED BANKROLL -- betting desk + trading desk in one number (the "one machine that keeps growing" view).
Reads, never writes, the sports-betting folder:
    ../sports betting/road.json        roll_now (PrizePicks cash the user last reported) + date
    ../sports betting/live_paper.jsonl betting ledger (net since the roll was set)
and this folder's results/trades.jsonl (LIVE trades only) + guard.json bankroll.
    python -m core.bankroll           # print it
    python -m core.bankroll --post    # also send to Discord/phone
"""
import os, sys, json, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BET = os.path.join(os.path.dirname(ROOT), "sports betting")


def betting():
    try:
        rd = json.load(open(os.path.join(BET, "road.json")))
        return float(rd.get("roll_now") or 0), rd.get("roll_now_date", "?")
    except Exception:
        return None, "sports betting/road.json not found"


def trading():
    from core import guard, ledger
    c = guard.cfg()
    return float(c["bankroll"]) + ledger.realized("LIVE"), ledger.realized("PAPER")


def main(post=False):
    b, bdate = betting(); t, paper = trading()
    total = (b or 0) + t
    lines = ["BANKROLL %s" % datetime.date.today().isoformat(),
             "  betting (PrizePicks, as of %s): $%.2f" % (bdate, b or 0),
             "  trading LIVE: $%.2f   (paper P/L to date: $%+.2f, not money)" % (t, paper),
             "  TOTAL: $%.2f" % total]
    print("\n".join(lines))
    if post:
        from core.notify import send
        send("DAILY", " | ".join(lines))


if __name__ == "__main__":
    main("--post" in sys.argv)
