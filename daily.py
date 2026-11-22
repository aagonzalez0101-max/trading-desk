"""THE DAILY DRIVER -- one command, like today.py on the betting desk.
    python daily.py            # status: guard, open trades, strategy records, next FOMC window, combined bankroll
    python daily.py --post     # same + send the summary to Discord/phone
    python daily.py paper      # also run one paper pass of every running paper strategy
"""
import sys, subprocess, datetime
from core import guard, ledger, bankroll

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
PAPER_STRATEGIES = [["-m", "strategies.pm_updown", "paper", "btc"]]       # add a line per running paper strategy


def phase2(post=False):
    """Phase 2 arena sleeves (run by the GitHub Action; this only reads results/phase2_equity.csv)."""
    import csv, os
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "phase2_equity.csv")
    if not os.path.exists(f):
        print("Phase 2 arena: no marks yet"); return
    rows = list(csv.DictReader(open(f)))
    last = max(r["date"] for r in rows)
    cur = [r for r in rows if r["date"] == last]
    txt = "; ".join("%s@%s $%s (%+.2f%%)" % (r["sleeve"], r["account"], r["equity"], float(r["return_pct"])) for r in cur)
    print("Phase 2 arena (%s close): %s" % (last, txt))
    if post:
        from core.notify import send
        send("DAILY", "Phase 2 paper sleeves %s: %s" % (last, txt))


def main():
    print("TRADING DESK %s CT" % datetime.datetime.now(CT).strftime("%a %m-%d %I:%M %p"))
    c = guard.cfg()
    print("guard: live_enabled=%s  live bankroll $%.2f  per-trade cap %.0f%%  daily stop -%.0f%%  halted_until=%s" % (
        c["live_enabled"], c["bankroll"], 100 * c["max_risk_per_trade_pct"], 100 * c["daily_loss_limit_pct"], c["halted_until"]))
    if "paper" in sys.argv:
        for args in PAPER_STRATEGIES:
            subprocess.run([sys.executable] + args)
    ledger.summary()
    phase2(post="--post" in sys.argv)
    try:
        out = subprocess.run([sys.executable, "run_fomc_paper.py"], capture_output=True, text=True, timeout=60).stdout.strip()
        print("FOMC drift:", out.splitlines()[-1] if out else "(needs Alpaca paper keys in .env)")
    except Exception as e:
        print("FOMC drift: not run (%s)" % e)
    bankroll.main("--post" in sys.argv)


if __name__ == "__main__":
    main()
