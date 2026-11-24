"""Pre-Fed-announcement drift on SPY, Alpaca PAPER, sized from a virtual $100 ledger.

The only strategy that passed the pre-registered research so far (round 3, R3-2; see
research/DAYTRADE_PLAN.md). Buy SPY with the whole ledger at ~1:55pm ET the day before a
scheduled FOMC announcement; sell at ~1:55pm ET on announcement day, before the 2:00pm
statement. Trades are tagged STRATEGY.

  python run_fomc_paper.py          # act now if inside a buy/sell window, else say when the next one is
  python run_fomc_paper.py --wait   # keep running and act when the window opens (start it that morning)
"""
import argparse
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from bot.alpaca import Paper
from bot.ledger import Ledger
from core import ledger
from core.notify import send as notify
import csv

from bot.data import OUT

# Self-contained on purpose (11/24): importing run_alpaca_paper / run_round3 pulled in yfinance, which GitHub's runner doesn't install,
# so the FOMC step crashed in the cloud. Same log file + columns as run_alpaca_paper.log().
LOG = OUT / "alpaca_paper_log.csv"
LOG_COLS = ["time", "week", "action", "symbol", "why", "order_id", "status", "filled_qty", "filled_price", "notional"]


def log(row: dict):
    new = not LOG.exists()
    with LOG.open("a", newline="") as f:
        w = csv.DictWriter(f, LOG_COLS)
        if new:
            w.writeheader()
        w.writerow({"time": datetime.now(NY).isoformat(timespec="seconds"), **row})


def fill_info(o: dict) -> dict:
    return {"order_id": o["id"], "status": o["status"], "filled_qty": o.get("filled_qty"), "filled_price": o.get("filled_avg_price")}

NY = ZoneInfo("America/New_York")
SYM = "SPY"
WINDOW = ((13, 50), (13, 58))      # act between 1:50 and 1:58pm ET
FOMC_SLEEVE = 1000.0               # the 10% of the $10k account that run_phase2.py leaves free
UPCOMING = ["2026-10-28", "2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
            "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08"]   # 2027 tentative per the Fed
ANNOUNCE = sorted({pd.Timestamp(d).date() for d in UPCOMING})          # only future meetings matter for paper trading


def prev_trading_day(api: Paper, d):
    cal = api._req("GET", "/v2/calendar", params={"start": str(d - timedelta(days=10)), "end": str(d - timedelta(days=1))})
    return pd.Timestamp(cal[-1]["date"]).date()


def plan(api: Paper, now: datetime):
    """Return ('buy'|'sell'|None, announcement date) for today."""
    today = now.date()
    for a in ANNOUNCE:
        if a == today:
            return "sell", a
        if a > today and prev_trading_day(api, a) == today:
            return "buy", a
    return None, next((a for a in ANNOUNCE if a > today), None)


def in_window(now):
    return WINDOW[0] <= (now.hour, now.minute) <= WINDOW[1]


def act(api: Paper, led: Ledger, action: str, a):
    if not api.clock()["is_open"]:
        print("Market closed; nothing sent.")
        return True
    if action == "buy" and led.qty(SYM) <= 0:
        spend = int(led.cash * 100) / 100
        o = api.wait_filled(api.buy(SYM, notional=spend)["id"])
        log({"week": f"FOMC {a}", "action": "buy", "symbol": SYM, "why": f"pre-FOMC drift: day before {a} statement",
             "notional": spend, **fill_info(o)})
        if float(o.get("filled_qty") or 0) > 0:
            led.fill(SYM, float(o["filled_qty"]), float(o["filled_avg_price"]), "STRATEGY", f"pre-FOMC buy for {a}")
            led.save()
            with ledger.using(ledger.PHASE2):
                ledger.open_trade("PAPER", "STRATEGY", "fomc_drift@10k", "alpaca", SYM, "LONG", float(o["filled_qty"]),
                                  float(o["filled_avg_price"]), spend, note=f"day before {a} statement")
            notify("FILL", f"FOMC drift: bought {float(o['filled_qty']):.4f} SPY @ ${float(o['filled_avg_price']):.2f} (${spend:,.2f}, paper)")
        print(f"Bought {o.get('filled_qty')} {SYM} @ {o.get('filled_avg_price')} (${spend}), status {o['status']}")
    elif action == "sell" and led.qty(SYM) > 0:
        o = api.wait_filled(api.sell(SYM, f"{led.qty(SYM):.9f}")["id"])
        log({"week": f"FOMC {a}", "action": "sell", "symbol": SYM, "why": f"pre-FOMC drift: exit before {a} 2pm statement",
             **fill_info(o)})
        if float(o.get("filled_qty") or 0) > 0:
            pnl = led.fill(SYM, -float(o["filled_qty"]), float(o["filled_avg_price"]), "STRATEGY", f"pre-FOMC sell {a}")
            led.save()
            with ledger.using(ledger.PHASE2):
                for r in ledger.open_trades("fomc_drift@10k"):
                    ledger.close_trade(r["id"], exit=float(o["filled_avg_price"]), net=pnl, note=f"sold before {a} 2pm statement")
            notify("EXIT", f"FOMC drift: sold SPY @ ${float(o['filled_avg_price']):.2f}, P&L ${pnl:+.2f} (paper)")
            print(f"Sold {o.get('filled_qty')} {SYM} @ {o.get('filled_avg_price')}: P&L ${pnl:+.4f}, ledger cash ${led.cash:.2f}")
    else:
        print(f"Nothing to do ({action}, holding {led.qty(SYM):.6f} {SYM}).")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", action="store_true")
    args = ap.parse_args()
    api, led = Paper("10k"), Ledger("fomc", start=FOMC_SLEEVE)     # user 11/22: FOMC is a sleeve in the $10k Main account
    while True:
        now = datetime.now(NY)
        action, a = plan(api, now)
        if action and in_window(now):
            act(api, led, action, a)
            return
        if not args.wait or not action or (now.hour, now.minute) > WINDOW[1]:
            when = f"{action} today 1:50-1:58pm ET" if action and (now.hour, now.minute) < WINDOW[0] else \
                f"next announcement {a}: buy the trading day before, sell on {a}, both at 1:50-1:58pm ET"
            print(f"Ledger cash ${led.cash:.2f}, holding {led.qty(SYM):.6f} {SYM}. {when}.")
            return
        time.sleep(20)


if __name__ == "__main__":
    main()
