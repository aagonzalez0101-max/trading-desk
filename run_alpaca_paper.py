"""Weekly trend+pullback ETF bot on an Alpaca PAPER account.

  python run_alpaca_paper.py              # trade last Friday's decision (market must be open)
  python run_alpaca_paper.py --dry-run    # show the decision, send nothing (works without keys)
  python run_alpaca_paper.py --force      # redo a week already marked done
  python run_alpaca_paper.py --sync-only  # just trim the Alpaca account to match the $100 ledger

Every trade is sized from a virtual $100 account (bot/ledger.py, results/ledger_etf.json),
not from the $100k paper balance, so paper behaves like the real $100 account will.

Run it once a week, any time the market is open Monday-Thursday after a Friday close
(Monday is closest to the backtest, which filled at Monday's close). Each week is traded
only once; the log goes to results/alpaca_paper_log.csv.
"""
import argparse
import csv
import json
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from bot.alpaca import Paper, have_keys
from bot.etf import ETFS
from bot.journal import WEEKLY
from bot.ledger import Ledger
from bot.weekly_live import decide
from bot.data import OUT

NY = ZoneInfo("America/New_York")
STATE = OUT / "alpaca_state.json"
LOG = OUT / "alpaca_paper_log.csv"
LOG_COLS = ["time", "week", "action", "symbol", "why", "order_id", "status", "filled_qty", "filled_price", "notional"]


def last_closed_friday(now: datetime) -> pd.Timestamp:
    f = now.date() - timedelta(days=(now.weekday() - 4) % 7)
    if now.date() == f and (now.hour, now.minute) < (16, 15):
        f -= timedelta(days=7)
    return pd.Timestamp(f)


def prices(friday: pd.Timestamp) -> pd.DataFrame:
    raw = yf.download(ETFS, start=friday - pd.Timedelta(days=3 * 365), auto_adjust=True, progress=False)
    px = raw["Close"][ETFS].dropna()
    px.index = px.index.tz_localize(None)
    px = px[px.index <= friday]
    if (friday - px.index[-1]).days > 3:
        raise SystemExit(f"Price data ends {px.index[-1]:%Y-%m-%d}, expected the week of {friday:%Y-%m-%d}. Stopping.")
    return px


def log(row: dict):
    new = not LOG.exists()
    with LOG.open("a", newline="") as f:
        w = csv.DictWriter(f, LOG_COLS)
        if new:
            w.writeheader()
        w.writerow({"time": datetime.now(NY).isoformat(timespec="seconds"), **row})


def fill_info(o: dict) -> dict:
    return {"order_id": o["id"], "status": o["status"], "filled_qty": o.get("filled_qty"),
            "filled_price": o.get("filled_avg_price")}


def record(led: Ledger, sym: str, sign: int, o: dict, tag: str, why: str):
    """Put whatever filled into the $100 ledger."""
    if float(o.get("filled_qty") or 0) > 0:
        led.fill(sym, sign * float(o["filled_qty"]), float(o["filled_avg_price"]), tag, why)
        led.save()
    if o["status"] != "filled":
        raise SystemExit(f"{sym} order ended '{o['status']}'; check the Alpaca dashboard. Ledger has what filled.")


def sync(api: Paper, led: Ledger, wk: str):
    """Sell any shares the Alpaca account holds beyond what the $100 ledger owns."""
    for sym, p in api.positions().items():
        extra = float(p["qty"]) - led.qty(sym)
        if extra > 1e-6:
            o = api.wait_filled(api.sell(sym, f"{extra:.9f}")["id"])
            log({"week": wk, "action": "resize", "symbol": sym, "why": "trim to $100-ledger size", **fill_info(o)})
            print(f"  trimmed {sym} by {extra:.6f} shares to match the $100 ledger: {o['status']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--sync-only", action="store_true")
    args = ap.parse_args()

    friday = last_closed_friday(datetime.now(NY))
    wk = f"{friday:%Y-%m-%d}"
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if state.get("last_week") == wk and not (args.force or args.dry_run or args.sync_only):
        print(f"Week of {wk} already traded. Nothing to do (use --force to redo).")
        return

    keys = have_keys()
    api = Paper() if keys else None
    led = Ledger("etf")
    held = {s for s in led.positions if s in ETFS}

    px = prices(friday)
    d = decide(px, held, friday)
    value = led.value({s: float(px[s].iloc[-1]) for s in led.positions})
    print(f"Decision from closes of week ending {d.week:%Y-%m-%d}")
    print(f"  $100 ledger (cycle {led.s['cycle']}): worth ${value:.2f} at Friday's close, cash ${led.cash:.2f}")
    print(f"  holding : {', '.join(sorted(held)) or 'nothing'}")
    for a, why in d.sells.items():
        print(f"  SELL {a}: {why}")
    print(f"  BUY  {d.buy}: {d.buy_why}" if d.buy else "  no new buy this week")

    if args.dry_run or not keys:
        if not keys:
            print("\nNo Alpaca keys in .env -> dry run only.")
        print("Dry run: no orders sent.")
        return

    if not api.clock()["is_open"]:
        print("Market is closed -> no orders sent. Run again during market hours (9:30-16:00 ET).")
        return
    if api.open_orders():
        raise SystemExit("There are open orders on the account; resolve them first. Nothing sent.")

    sync(api, led, wk)
    if args.sync_only:
        return

    for a, why in d.sells.items():
        o = api.wait_filled(api.sell(a, f"{led.qty(a):.9f}")["id"])
        log({"week": wk, "action": "sell", "symbol": a, "why": why, **fill_info(o)})
        record(led, a, -1, o, "STRATEGY", why)
        print(f"  sold {a}: {o['status']} {o.get('filled_qty')} @ {o.get('filled_avg_price')}")

    if d.buy:
        value = led.value({s: float(px[s].iloc[-1]) for s in led.positions})
        spend = math.floor(min(led.cash, value / WEEKLY.slots) * 100) / 100
        if spend < 1.0:
            print(f"  skip buy {d.buy}: only ${spend:.2f} available (Alpaca minimum is $1)")
            log({"week": wk, "action": "skip_buy", "symbol": d.buy, "why": f"only ${spend:.2f} in the $100 ledger"})
        elif not api.asset(d.buy).get("fractionable"):
            print(f"  skip buy {d.buy}: not fractionable, and ${spend:.2f} won't buy a whole share")
            log({"week": wk, "action": "skip_buy", "symbol": d.buy, "why": "not fractionable"})
        else:
            o = api.wait_filled(api.buy(d.buy, notional=spend)["id"])
            log({"week": wk, "action": "buy", "symbol": d.buy, "why": d.buy_why, "notional": spend, **fill_info(o)})
            record(led, d.buy, 1, o, "STRATEGY", d.buy_why)
            print(f"  bought {d.buy}: {o['status']} {o.get('filled_qty')} @ {o.get('filled_avg_price')} (${spend:.2f})")

    STATE.write_text(json.dumps({"last_week": wk}))
    print(f"Done. Logged to {LOG.name}; $100 ledger cash now ${led.cash:.2f}.")


if __name__ == "__main__":
    main()
