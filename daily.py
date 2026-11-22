"""THE DAILY DRIVER -- one command, like today.py on the betting desk.
    python daily.py            # status: guard, open trades, strategy records, next FOMC window, combined bankroll
    python daily.py --post     # same + send the summary to Discord/phone
    python daily.py paper      # also run one paper pass of every running paper strategy
"""
import sys, subprocess, datetime
from core import guard, ledger, bankroll

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
PAPER_STRATEGIES = [["-m", "strategies.pm_updown", "paper", "btc"]]       # add a line per running paper strategy


def main():
    print("TRADING DESK %s CT" % datetime.datetime.now(CT).strftime("%a %m-%d %I:%M %p"))
    c = guard.cfg()
    print("guard: live_enabled=%s  live bankroll $%.2f  per-trade cap %.0f%%  daily stop -%.0f%%  halted_until=%s" % (
        c["live_enabled"], c["bankroll"], 100 * c["max_risk_per_trade_pct"], 100 * c["daily_loss_limit_pct"], c["halted_until"]))
    if "paper" in sys.argv:
        for args in PAPER_STRATEGIES:
            subprocess.run([sys.executable] + args)
    ledger.summary()
    try:
        out = subprocess.run([sys.executable, "run_fomc_paper.py"], capture_output=True, text=True, timeout=60).stdout.strip()
        print("FOMC drift:", out.splitlines()[-1] if out else "(needs Alpaca paper keys in .env)")
    except Exception as e:
        print("FOMC drift: not run (%s)" % e)
    bankroll.main("--post" in sys.argv)


if __name__ == "__main__":
    main()
