"""PHASE 2 PAPER ARENA -- the slow monthly ETF strategies that PASSED run_phase2_backtest.py, traded on Alpaca PAPER.

Accounts (user 11/22): "500" = Real-Start ($500, what a first real transfer would look like: fractional shares, $1 minimums,
cash-only buying power) and "10k" = Main ($10,000, the main record; the pre-FOMC drift sleeve also lives here). The $100,000
"full-time scale" view is COMPUTED from the 10k sleeves (liquid ETFs fill the same at any paper size) -- no account.
Each passing strategy gets a virtual sleeve (bot/ledger.py) in BOTH accounts: 90% of the account split evenly between the
sleeves (10% buffer: rounding, the $500 account's cash-only sequencing, and the FOMC sleeve in the 10k account).

Run once a day after the US close (GitHub Action .github/workflows/phase2.yml, weekdays 21:30 UTC):
  1. reconcile: last run's orders -> fills into each sleeve at the real fill price, slippage vs the decision close logged
  2. place any buys held back for buying power (the $500 account can't buy until its sells have filled)
  3. mark every sleeve to market -> results/phase2_equity.csv (+ $100k shadow)
  4. after a month's last close (or the first run after it, if a run was missed): new target weights from the SAME rule
     code the backtest used (strategies/phase2.py), trade the difference; queued market orders fill at the next open
  5. on the first run of a new month: health review (monthly) / grading (Jan, Apr, Jul, Oct) -> results/phase2_reviews.md
    python run_phase2.py                 # the daily pass
    python run_phase2.py --status        # print sleeves, no orders
    python run_phase2.py --review [quarterly]   # write a review now
Paper only: bot/alpaca.py can only talk to paper-api.alpaca.markets.
"""
import csv, datetime, json, os, sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from bot.alpaca import Paper
from bot.ledger import Ledger
from core import guard, ledger
from strategies import phase2 as P

ROOT = Path(__file__).resolve().parent
RES = ROOT / "results"
STATE = RES / "phase2_state.json"
EQUITY = RES / "phase2_equity.csv"
FILLS = RES / "phase2_fills.csv"
REVIEWS = RES / "phase2_reviews.md"
CT = ZoneInfo("America/Chicago")

SLEEVES = ["risk_parity8"]                          # 11/22 backtest: the only candidate that passed (tsmom_etf8 failed its placebo)
ACCOUNTS = {"500": 500.0, "10k": 10000.0}
INVESTED = 0.90                                     # share of each account split between the sleeves
MIN_ORDER = 1.00                                    # Alpaca's fractional minimum ($)
SHADOW = 100000.0


def now_ct():
    return datetime.datetime.now(CT)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"started": now_ct().date().isoformat(), "last_decision": None, "last_review": None,
            "accounts": {a: {"pending": [], "deferred": []} for a in ACCOUNTS}}


def save_state(s):
    STATE.write_text(json.dumps(s, indent=1))


def sleeve(strat, acct):
    return Ledger(f"p2_{strat}_{acct}", start=round(ACCOUNTS[acct] * INVESTED / len(SLEEVES), 2))


def append_csv(path, row):
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def notify(kind, text):
    try:
        from core.notify import send
        send(kind, text)
    except Exception as e:
        print("notify failed:", e)


# ------------------------------------------------------------------ prices + calendar
def closes(api):
    """daily adjusted closes for the whole universe, ~500 calendar days (rules need <= 331 trading days)."""
    end = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=20)
    start = (end - datetime.timedelta(days=520)).date()
    raw = api.daily_bars(P.UNIVERSE, start, end.isoformat(timespec="seconds").replace("+00:00", "Z"))
    df = pd.DataFrame({s: pd.Series({pd.Timestamp(d): c for d, c, _ in v}) for s, v in raw.items()}).sort_index()
    # GitHub's cron can fire hours late (11/23: the 21:30 UTC run fired at 05:23). If a run lands while the market is open, today's daily bar is
    # still forming -- drop it so every decision uses completed closes only, exactly like the backtest.
    if api.clock().get("is_open") and len(df) and df.index[-1].date() == datetime.datetime.now(ZoneInfo("America/New_York")).date():
        df = df.iloc[:-1]
    return df


def decision_month(api, last_bar):
    """the YYYY-MM of the latest month-end trading day <= last_bar (the decision that should already have been made)."""
    cal = [pd.Timestamp(d["date"]) for d in api.calendar(last_bar - pd.Timedelta(days=70), last_bar + pd.Timedelta(days=10))]
    me = [d for i, d in enumerate(cal[:-1]) if d.month != cal[i + 1].month and d <= last_bar]
    return me[-1].strftime("%Y-%m")


# ------------------------------------------------------------------ reconcile fills
def reconcile(api, acct, st):
    left = []
    for o in st["pending"]:
        r = api.order(o["id"])
        if r["status"] not in ("filled", "canceled", "expired", "rejected", "done_for_day"):
            left.append(o); continue
        fq = float(r.get("filled_qty") or 0); px = float(r.get("filled_avg_price") or 0)
        f = fq / abs(o["net_qty"]) if o["net_qty"] else 0
        for strat, q in o["legs"].items():
            if fq > 0:
                led = sleeve(strat, acct)
                led.fill(o["symbol"], q * f, px, "STRATEGY", f"{o['why']} (order {r['status']})", when=r.get("filled_at"))
                led.save()
        slip = (px / o["ref"] - 1) * (1 if o["side"] == "buy" else -1) * 1e4 if fq > 0 else None
        append_csv(FILLS, {"time": now_ct().isoformat(timespec="seconds"), "account": acct, "symbol": o["symbol"],
                           "side": o["side"], "status": r["status"], "want_qty": round(abs(o["net_qty"]), 6),
                           "filled_qty": fq, "ref_close": o["ref"], "fill_price": px or "",
                           "cost_bps": "" if slip is None else round(slip, 1), "placed": o["placed"],
                           "filled_at": r.get("filled_at") or "", "decision": o["decision"]})
        print(f"  [{acct}] {o['side']} {o['symbol']}: {r['status']} {fq:.6f} @ {px:.2f} (decision close {o['ref']:.2f})")
    done = len(st["pending"]) - len(left)
    st["pending"] = left
    return done


# ------------------------------------------------------------------ orders
def place(api, acct, st, legs_by_sym, ref, decision, why):
    """legs_by_sym: {sym: {strat: share qty (+buy/-sell)}}. Sells first; buys only up to cash buying power, rest deferred."""
    held = {s: float(p["qty"]) for s, p in api.positions().items()}
    sells = {s: l for s, l in legs_by_sym.items() if sum(l.values()) < 0}
    buys = {s: l for s, l in legs_by_sym.items() if sum(l.values()) > 0}
    placed = []
    for sym, legs in sells.items():
        net = sum(legs.values())
        qty = min(-net, held.get(sym, 0.0))
        if qty * ref[sym] < MIN_ORDER:
            continue
        r = api.sell(sym, f"{qty:.9f}".rstrip("0").rstrip("."))
        st["pending"].append(dict(id=r["id"], symbol=sym, side="sell", net_qty=-qty, legs=legs, ref=ref[sym],
                                  placed=now_ct().isoformat(timespec="seconds"), decision=decision, why=why))
        placed.append(f"sell {sym} ${qty * ref[sym]:.0f}")
    bp = float(api.account()["non_marginable_buying_power"]) - 1.0   # cash only: never let the sleeves borrow
    for sym, legs in buys.items():
        net = sum(legs.values()); notional = int(net * ref[sym] * 100) / 100
        if notional < MIN_ORDER:
            continue
        if notional > bp:
            st["deferred"].append(dict(symbol=sym, legs=legs, decision=decision, why=why)); continue
        r = api.buy(sym, notional=notional); bp -= notional
        st["pending"].append(dict(id=r["id"], symbol=sym, side="buy", net_qty=net, legs=legs, ref=ref[sym],
                                  placed=now_ct().isoformat(timespec="seconds"), decision=decision, why=why))
        placed.append(f"buy {sym} ${notional:.0f}")
    return placed


def place_deferred(api, acct, st, ref):
    if not st["deferred"] or st["pending"]:          # wait until the sells have filled
        return []
    d, st["deferred"] = st["deferred"], []
    out = []
    for x in d:
        # re-size from today's sleeve state so a sleeve never buys more than its cash
        legs = {}
        for strat, q in x["legs"].items():
            led = sleeve(strat, acct)
            legs[strat] = min(q, max(0.0, led.cash - 0.01) / ref[x["symbol"]])
        out += place(api, acct, st, {x["symbol"]: legs}, ref, x["decision"], x["why"] + " (deferred for buying power)")
    return out


def rebalance(api, acct, st, px, decision):
    ref = px.iloc[-1].to_dict()
    legs_by_sym = {}; lines = []
    for strat in SLEEVES:
        led = sleeve(strat, acct)
        v = led.value(ref)
        tgt = P.RULES[strat](px)
        name = f"p2_{strat}@{acct}"
        with ledger.using(ledger.PHASE2):
            ok, why = guard.allow("PAPER", v, strategy=name)
        if not ok:
            lines.append(f"{strat}: guard says no ({why})"); continue
        # the ledger record: one row per sleeve per month (open now at this value, closed at the next decision)
        with ledger.using(ledger.PHASE2):
            for r in ledger.open_trades(name):
                ledger.close_trade(r["id"], exit=round(v, 2), net=v - r["stake"], note=f"month to {decision}")
            ledger.open_trade("PAPER", "STRATEGY", name, "alpaca", "sleeve", "LONG", 1, round(v, 2), v,
                              note="target " + " ".join(f"{a} {w:.0%}" for a, w in tgt.sort_values(ascending=False).items()))
        for sym in set(tgt.index) | set(led.positions):
            want = tgt.get(sym, 0.0) * v / ref[sym]
            dq = want - led.qty(sym)
            if abs(dq * ref[sym]) >= MIN_ORDER:
                legs_by_sym.setdefault(sym, {})[strat] = dq
        lines.append(f"{strat} ${v:,.2f}: " + ", ".join(f"{a} {w:.0%}" for a, w in tgt.sort_values(ascending=False).items()))
    placed = place(api, acct, st, legs_by_sym, ref, decision, f"monthly rebalance {decision}")
    return lines, placed


# ------------------------------------------------------------------ mark to market
def mark(acct, px, write=True):
    ref = px.iloc[-1].to_dict(); day = px.index[-1].date().isoformat(); rows = []
    for strat in SLEEVES:
        led = sleeve(strat, acct); v = led.value(ref)
        row = {"date": day, "account": acct, "sleeve": strat, "equity": round(v, 2), "start": led.start,
               "return_pct": round(100 * (v / led.start - 1), 3), "cash": round(led.cash, 2),
               "shadow_100k": round(SHADOW * v / led.start, 2) if acct == "10k" else ""}
        rows.append(row)
    if acct == "10k" and (RES / "ledger_fomc.json").exists():
        led = Ledger("fomc"); v = led.value(ref)
        rows.append({"date": day, "account": acct, "sleeve": "fomc_drift", "equity": round(v, 2), "start": led.start,
                     "return_pct": round(100 * (v / led.start - 1), 3), "cash": round(led.cash, 2), "shadow_100k": ""})
    if not write:
        return rows
    old = pd.read_csv(EQUITY) if EQUITY.exists() else pd.DataFrame()
    if len(old):
        old = old[~((old["date"] == day) & (old["account"].astype(str) == acct))]
    pd.concat([old, pd.DataFrame(rows)]).to_csv(EQUITY, index=False)
    return rows


# ------------------------------------------------------------------ grading
def bands(strat, months):
    """the backtest's normal range for a `months`-long stretch: 5th / 50th / 95th percentile of every rolling window."""
    m = pd.read_csv(RES / "phase2_backtest_monthly.csv", index_col=0)[strat].dropna() / 100
    k = max(1, months)
    roll = (1 + m).rolling(k).apply(np.prod, raw=True).dropna() - 1
    eq = (1 + m).cumprod(); worst = float((eq / eq.cummax() - 1).min())
    return np.percentile(roll, [1, 5, 50, 95, 99]), worst


def review(kind=None):
    s = load_state()
    today = now_ct().date()
    kind = kind or ("quarterly" if today.month in (1, 4, 7, 10) else "monthly")
    eq = pd.read_csv(EQUITY) if EQUITY.exists() else pd.DataFrame()
    fills = pd.read_csv(FILLS) if FILLS.exists() else pd.DataFrame()
    started = pd.Timestamp(s["started"])
    months = max(1, (today.year - started.year) * 12 + today.month - started.month)
    lines = [f"\n## {kind.upper()} review {today} ({months} month(s) since {s['started']})", ""]
    # execution health
    if len(fills):
        f = fills.copy(); f["cost_bps"] = pd.to_numeric(f["cost_bps"], errors="coerce")
        last = f[pd.to_datetime(f["time"].str[:10]) >= pd.Timestamp(today) - pd.Timedelta(days=95 if kind == "quarterly" else 35)]
        bad = last[last["status"] != "filled"]
        lines.append(f"Execution: {len(last)} orders, {len(bad)} not fully filled; average fill vs the decision close "
                     f"{last['cost_bps'].mean():+.0f} bps (backtest assumes 10 bps cost; the overnight gap adds noise of "
                     f"roughly +-30-60 bps per order that averages out)." if len(last) else "Execution: no orders in the period.")
        exec_ok = len(bad) == 0 and (len(last) == 0 or abs(last["cost_bps"].mean()) < 75)
    else:
        lines.append("Execution: no orders yet."); exec_ok = True
    lines += ["", "| sleeve | account | equity | since start | backtest normal range (5th..95th) | verdict |", "|---|---|---|---|---|---|"]
    verdicts = []
    for strat in SLEEVES:
        (p1, p5, p50, p95, p99), worst = bands(strat, months)
        for acct in ACCOUNTS:
            e = eq[(eq["sleeve"] == strat) & (eq["account"].astype(str) == acct)] if len(eq) else eq
            if not len(e):
                continue
            r = float(e["return_pct"].iloc[-1]) / 100
            v = "normal" if p5 <= r <= p95 else ("unusual, still inside 1-99%" if p1 <= r <= p99 else "OUTSIDE the backtest range")
            if kind == "quarterly":
                v = ("KEEP" if p1 <= r and exec_ok else "REVIEW: cut or rename (user decides)") + f" ({v})"
            verdicts.append(f"{strat}@{acct} {r:+.1%} {v.split(' (')[0]}")
            lines.append(f"| {strat} | {acct} | ${float(e['equity'].iloc[-1]):,.2f} | {r:+.1%} | {p5:+.1%} .. {p95:+.1%} "
                         f"(median {p50:+.1%}; backtest worst drawdown {worst:.0%}) | {v} |")
    lines.append("")
    lines.append("Rule: only a QUARTERLY review may cut or change a sleeve, and a changed rule is a NEW name with a fresh record.")
    REVIEWS.open("a", encoding="utf-8").write("\n".join(lines) + "\n")
    s["last_review"] = today.strftime("%Y-%m"); save_state(s)
    print("\n".join(lines))
    notify("DAILY", f"Phase 2 {kind} review: " + ("execution OK" if exec_ok else "EXECUTION PROBLEM") + " | " + "; ".join(verdicts))


# ------------------------------------------------------------------ main
def daily(status_only=False):
    s = load_state()
    for acct in ACCOUNTS:
        s["accounts"].setdefault(acct, {"pending": [], "deferred": []})
    api0 = Paper("10k")
    px = closes(api0)
    last = px.index[-1]
    dm = decision_month(api0, last)
    print(f"PHASE 2 ARENA {now_ct():%a %m-%d %I:%M %p} CT | prices to {last.date()} | decision due for {dm}, "
          f"last made {s['last_decision']}")
    msgs, errors = [], []
    for acct in ACCOUNTS:
        st = s["accounts"][acct]
        try:
            api = Paper(acct)
            if not status_only:
                n = reconcile(api, acct, st)
                if n:
                    msgs.append(f"[{acct}] {n} order(s) settled")
                d = place_deferred(api, acct, st, px.iloc[-1].to_dict())
                if d:
                    msgs.append(f"[{acct}] deferred: " + ", ".join(d))
            for r in mark(acct, px, write=not status_only):
                print(f"  [{acct}] {r['sleeve']:<14} ${r['equity']:>10,.2f}  {r['return_pct']:+.2f}%" +
                      (f"   ($100k view ${r['shadow_100k']:,.0f})" if r["shadow_100k"] != "" else ""))
            if status_only or st.get("last_decision") == dm:
                continue
            if st["pending"]:
                msgs.append(f"[{acct}] rebalance waits: {len(st['pending'])} order(s) still open"); continue
            st["deferred"] = []                          # a new decision replaces any buys still waiting from the last one
            lines, placed = rebalance(api, acct, st, px, dm)
            st["last_decision"] = dm
            print(f"  [{acct}] rebalance for {dm} on {last.date()} closes:\n    " + "\n    ".join(lines))
            print(f"    orders: {', '.join(placed) or 'none'}" + (f"; deferred {len(st['deferred'])}" if st["deferred"] else ""))
            msgs.append(f"[{acct}] rebalance {dm} on {last.date()} closes: {len(placed)} orders queued for the next open" +
                        (f", {len(st['deferred'])} buys wait for cash" if st["deferred"] else ""))
        except Exception as e:                           # one account failing must not stop the other
            errors.append(f"[{acct}] {type(e).__name__}: {e}")
            print("ERROR", errors[-1])
        finally:
            if not status_only:
                save_state(s)                            # after EVERY account: placed orders are never forgotten
    if all(s["accounts"][a].get("last_decision") == dm for a in ACCOUNTS):
        s["last_decision"] = dm
    if not status_only:
        save_state(s)
    if msgs:
        notify("FILL", "Phase 2: " + " | ".join(msgs))
    if errors:
        notify("ERROR", "Phase 2: " + " | ".join(errors))
    if not status_only and s.get("last_review") != now_ct().strftime("%Y-%m") and s["last_decision"] and             pd.Timestamp(s["started"]).strftime("%Y-%m") != now_ct().strftime("%Y-%m"):
        review()
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    # ONE runner only: the GitHub Action owns the state files. A second copy running here would trade the same sleeves twice.
    if not ("--status" in sys.argv or os.getenv("GITHUB_ACTIONS") == "true" or "--i-am-the-only-runner" in sys.argv):
        sys.exit("run_phase2.py trades only inside the GitHub Action (it owns results/phase2_state.json). "
                 "Use --status here, or trigger the workflow: gh workflow run phase2.yml")
    if "--review" in sys.argv:
        review("quarterly" if "quarterly" in sys.argv else None)
    else:
        daily("--status" in sys.argv)
