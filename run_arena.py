"""Live paper ARENA: six scalping / day-trading strategies forward-tested at once on the
OANDA practice account, at cents-size (100 units: 1 pip = ~1 cent).

  python run_arena.py            # run all six (Ctrl+C to stop; open trades resume on restart)
  python run_arena.py --report   # scoreboard

Why live: a live market can't be curve-fit. Each strategy gets its own pair because OANDA US
accounts can't hold opposite trades on the same pair (FIFO / no hedging).
Verdict rule (fixed now): a strategy WORKS only after >= 100 live trades with an average
trade above zero after costs and t-stat >= 2. Under 100 trades = not enough evidence.

Shared rules: decide on a complete candle, enter at market with stop and target attached at
OANDA, close at the time stop. Skip when the live spread is over 2x normal, on weekends, and
20:00-22:59 UTC (daily rollover, widest spreads). One open trade per strategy.
"""
import argparse
import csv
import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from bot.data import OUT, SPREAD_PIPS, pip_size
from bot.oanda import Practice

UNITS = 100
STATE = OUT / "arena_state.json"
LOG = OUT / "arena_log.csv"
COLS = ["time", "strategy", "pair", "event", "side", "units", "expected_px", "bid", "ask", "fill_px",
        "slippage_pips", "spread_pips", "stop", "target", "exit_px", "net_pips", "realized_usd", "minutes", "note"]


def bars(api, pair, gran, n):
    cs = [c for c in api.candles(pair, gran, count=n + 1) if c["complete"]]
    f = lambda side, k: np.array([float(c[side][k]) for c in cs])
    d = {k: (f("bid", k) + f("ask", k)) / 2 for k in "ohlc"}
    d["spread"] = f("ask", "c") - f("bid", "c")
    d["time"] = [pd.Timestamp(c["time"]) for c in cs]
    return d


def atr(d, n=14):
    h, l, c = d["h"], d["l"], d["c"]
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return tr[-n:].mean()


def ema(x, n):
    out = np.empty_like(x)
    out[0], a = x[0], 2 / (n + 1)
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


# ---------------------------------------------------------------- the six strategies
# Each returns (side, stop, target, max_minutes, note) or None, using mid prices.
def fade_m1(d, mem, pip):
    w, c = d["c"][-20:], d["c"][-1]
    ma, sd = w.mean(), w.std(ddof=1)
    dist = abs(c - ma)
    if dist < 3 * d["spread"][-1]:
        return None
    if c > ma + 2.5 * sd:
        return -1, c + dist, ma, 15, "1-min spike above 20-bar avg +2.5sd"
    if c < ma - 2.5 * sd:
        return 1, c - dist, ma, 15, "1-min spike below 20-bar avg -2.5sd"


def breakout_m1(d, mem, pip):
    c, hi, lo, a = d["c"][-1], d["c"][-16:-1].max(), d["c"][-16:-1].min(), atr(d, 15)
    if a < 2 * d["spread"][-1]:
        return None
    if c > hi:
        return 1, c - a, c + 1.5 * a, 30, "1-min close above 15-bar high"
    if c < lo:
        return -1, c + a, c - 1.5 * a, 30, "1-min close below 15-bar low"


def ema_cross_m5(d, mem, pip):
    f, s = ema(d["c"], 9), ema(d["c"], 21)
    a, c = atr(d, 14), d["c"][-1]
    if f[-2] <= s[-2] and f[-1] > s[-1]:
        return 1, c - 1.5 * a, c + 3 * a, 120, "5-min EMA9 crossed above EMA21"
    if f[-2] >= s[-2] and f[-1] < s[-1]:
        return -1, c + 1.5 * a, c - 3 * a, 120, "5-min EMA9 crossed below EMA21"


def rsi_m5(d, mem, pip):
    diff = np.diff(d["c"][-15:])
    up, dn = diff.clip(min=0).mean(), (-diff).clip(min=0).mean()
    rsi = 100 if dn == 0 else 100 - 100 / (1 + up / dn)
    a, c = atr(d, 14), d["c"][-1]
    if rsi < 20:
        return 1, c - 1.5 * a, c + 1.5 * a, 60, f"5-min RSI {rsi:.0f} < 20 (oversold)"
    if rsi > 80:
        return -1, c + 1.5 * a, c - 1.5 * a, 60, f"5-min RSI {rsi:.0f} > 80 (overbought)"


def round_bounce_m5(d, mem, pip):
    step, c0, h, l, c = 100 * pip, d["c"][-2], d["h"][-1], d["l"][-1], d["c"][-1]
    up, dn = np.ceil(c0 / step - 1e-9) * step, np.floor(c0 / step + 1e-9) * step
    day = str(d["time"][-1].date())
    used = mem.setdefault("used", [])
    if c0 <= up - 5 * pip and h >= up and c < up and f"{day}:{up:.5f}" not in used:
        used.append(f"{day}:{up:.5f}")
        return -1, up + 15 * pip, c - 20 * pip, 120, f"5-min bar rejected round number {up:.3f}"
    if c0 >= dn + 5 * pip and l <= dn and c > dn and f"{day}:{dn:.5f}" not in used:
        used.append(f"{day}:{dn:.5f}")
        return 1, dn - 15 * pip, c + 20 * pip, 120, f"5-min bar rejected round number {dn:.3f}"


def london_breakout_h1(d, mem, pip):
    t = d["time"][-1]
    day = t.normalize()
    if not (7 <= t.hour <= 10) or mem.get("done") == str(day.date()):
        return None
    asia = [i for i, x in enumerate(d["time"]) if x.normalize() == day and x.hour <= 6]
    if len(asia) < 5:
        return None
    hi, lo = d["h"][asia].max(), d["l"][asia].min()
    width, c = hi - lo, d["c"][-1]
    if not (15 * pip <= width <= 60 * pip):
        return None
    minutes = max(int((day + pd.Timedelta(hours=16) - t).total_seconds() // 60) - 60, 30)
    if c > hi:
        mem["done"] = str(day.date())
        return 1, lo, c + width, minutes, f"broke Asian range high {hi:.5f} at London open"
    if c < lo:
        mem["done"] = str(day.date())
        return -1, hi, c - width, minutes, f"broke Asian range low {lo:.5f} at London open"


STRATEGIES = {  # name: (pair, granularity, bars needed, function)
    "fade_m1":         ("EUR_USD", "M1", 30, fade_m1),
    "breakout_m1":     ("GBP_USD", "M1", 30, breakout_m1),
    "ema_cross_m5":    ("USD_JPY", "M5", 80, ema_cross_m5),
    "rsi_m5":          ("NZD_USD", "M5", 30, rsi_m5),
    "round_bounce_m5": ("USD_CAD", "M5", 5, round_bounce_m5),
    "london_brk_h1":   ("AUD_USD", "H1", 14, london_breakout_h1),
}


def save(state):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE)  # atomic swap: a crash mid-save can't leave a half-written file


def log(row):
    new = not LOG.exists()
    with LOG.open("a", newline="") as f:
        w = csv.DictWriter(f, COLS)
        if new:
            w.writeheader()
        w.writerow({"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **row})


def decimals(pair):
    return 3 if pair.endswith("JPY") else 5


def try_open(api, name, pair, sig, st):
    side, stop, target, minutes, note = sig
    pip = pip_size(pair)
    bid, ask, ok = api.price(pair)
    if not ok or (ask - bid) > 2 * SPREAD_PIPS[pair] * pip:
        return
    entry = ask if side == 1 else bid
    if (side == 1 and not (stop < entry < target)) or (side == -1 and not (target < entry < stop)):
        log({"strategy": name, "pair": pair, "event": "skip", "side": side, "bid": bid, "ask": ask, "note": "price already past stop/target"})
        return
    resp = api.market_order(pair, side * UNITS, stop, target, decimals(pair))
    fill = resp.get("orderFillTransaction")
    if not fill or "tradeOpened" not in fill:
        log({"strategy": name, "pair": pair, "event": "rejected", "side": side,
             "note": json.dumps(resp.get("orderCancelTransaction", resp))[:200]})
        return
    px = float(fill["price"])
    st["open"] = {"trade_id": fill["tradeOpened"]["tradeID"], "opened": time.time(), "side": side,
                  "entry": px, "minutes": minutes, "stop": stop, "target": target}
    log({"strategy": name, "pair": pair, "event": "open", "side": side, "units": side * UNITS, "bid": bid, "ask": ask,
         "fill_px": px, "slippage_pips": round(side * (px - entry) / pip, 2), "spread_pips": round((ask - bid) / pip, 2),
         "stop": round(stop, 5), "target": round(target, 5), "note": note})
    print(f"{datetime.now(timezone.utc):%H:%M:%S} {name}: {'BUY' if side == 1 else 'SELL'} {pair} @ {px} ({note})", flush=True)


def check_open(api, name, pair, st):
    o = st["open"]
    tr = api.trade(o["trade_id"])
    why = None
    if tr["state"] == "CLOSED":
        why = "stop/target hit"
    elif time.time() - o["opened"] >= o["minutes"] * 60:
        api.close_trade(o["trade_id"])
        tr, why = api.trade(o["trade_id"]), f"{o['minutes']}-min time stop"
    if why:
        px, pip = float(tr["averageClosePrice"]), pip_size(pair)
        net = o["side"] * (px - o["entry"]) / pip
        log({"strategy": name, "pair": pair, "event": "close", "side": o["side"], "units": o["side"] * UNITS,
             "exit_px": px, "net_pips": round(net, 2), "realized_usd": float(tr["realizedPL"]),
             "minutes": round((time.time() - o["opened"]) / 60, 1), "note": why})
        print(f"{datetime.now(timezone.utc):%H:%M:%S} {name}: closed {pair} {net:+.1f} pips (${float(tr['realizedPL']):+.4f}), {why}", flush=True)
        del st["open"]


def run(api):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    last = {}
    print(f"Arena running {len(STRATEGIES)} strategies at {UNITS} units. Ctrl+C to stop.", flush=True)
    while True:
        try:
            now = datetime.now(timezone.utc)
            trading_hours = now.weekday() < 5 and not (20 <= now.hour <= 22)
            for name, (pair, gran, n, fn) in STRATEGIES.items():
                st = state.setdefault(name, {})
                if "open" in st:
                    check_open(api, name, pair, st)
                    continue
                if not trading_hours:
                    continue
                d = bars(api, pair, gran, n)
                if len(d["c"]) < min(n, 20) or d["time"][-1] == last.get(name):
                    continue
                last[name] = d["time"][-1]
                sig = fn(d, st.setdefault("mem", {}), pip_size(pair))
                if sig:
                    try_open(api, name, pair, sig, st)
            save(state)
            time.sleep(5)
        except KeyboardInterrupt:
            save(state)
            print("Stopped. Open trades keep their stop/target at OANDA and resume on restart.")
            return
        except Exception as e:
            log({"event": "error", "note": str(e)[:200]})
            print(f"error: {e}; retrying in 30s", flush=True)
            time.sleep(30)


def report():
    if not LOG.exists():
        print("No trades yet.")
        return
    df = pd.read_csv(LOG)
    c = df[df.event == "close"]
    opens = df[df.event == "open"]
    rows = []
    for name in STRATEGIES:
        g, o = c[c.strategy == name], opens[opens.strategy == name]
        n = len(g)
        t = g.net_pips.mean() / g.net_pips.std() * np.sqrt(n) if n > 1 and g.net_pips.std() > 0 else float("nan")
        verdict = "need 100 trades" if n < 100 else ("WORKS" if g.net_pips.mean() > 0 and t >= 2 else "DOESN'T WORK")
        rows.append({"strategy": name, "pair": STRATEGIES[name][0], "trades": n,
                     "win_rate": (g.net_pips > 0).mean() if n else float("nan"),
                     "avg_pips": g.net_pips.mean() if n else float("nan"), "total_usd": g.realized_usd.sum(),
                     "avg_spread_paid": o.spread_pips.mean() if len(o) else float("nan"),
                     "avg_slippage": o.slippage_pips.mean() if len(o) else float("nan"), "t_stat": t, "verdict": verdict})
    pd.set_option("display.width", 220)
    print(pd.DataFrame(rows).to_string(index=False, formatters={
        "win_rate": "{:.0%}".format, "avg_pips": "{:+.2f}".format, "total_usd": "${:+.4f}".format,
        "avg_spread_paid": "{:.2f}".format, "avg_slippage": "{:+.2f}".format, "t_stat": "{:+.2f}".format}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    report() if args.report else run(Practice())
