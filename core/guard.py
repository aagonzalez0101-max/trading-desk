"""RISK GUARD -- the rules the bot cannot override. Every strategy calls guard.allow() before placing anything.
Config: guard.json (created with safe defaults on first run). LIVE money is OFF until the user flips live_enabled himself.
    {"live_enabled": false,            # real-money orders blocked unless the user sets true
     "bankroll": 0.0,                # LIVE trading bankroll ($), the user updates it
     "max_risk_per_trade_pct": 0.02,   # 2% of bankroll at risk per trade (the old desk's non-negotiable 1-2%)
     "daily_loss_limit_pct": 0.06,     # stop everything for the day after -6%
     "max_open_trades": 3,
     "halted_until": null}
    from core import guard
    ok, why = guard.allow("LIVE", stake=1.50)
    python -m core.guard            # print status
"""
import os, sys, json, datetime
from core import ledger

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "guard.json")
DEFAULT = {"live_enabled": False, "bankroll": 0.0, "max_risk_per_trade_pct": 0.02, "daily_loss_limit_pct": 0.06,
           "max_open_trades": 3, "halted_until": None}


def cfg():
    if not os.path.exists(CFG):
        json.dump(DEFAULT, open(CFG, "w"), indent=1)
    c = dict(DEFAULT); c.update(json.load(open(CFG)))
    return c


def allow(kind, stake, strategy=None):
    """-> (ok, reason). PAPER trades only check open-trade count; LIVE trades check every rule.
    strategy= counts only that strategy's open trades (Phase 2 sleeves hold one month-long record each)."""
    c = cfg(); now = datetime.datetime.now(CT)
    if c.get("halted_until") and now.isoformat() < c["halted_until"]:
        return False, "halted until %s" % c["halted_until"]
    if len([r for r in ledger.open_trades(strategy) if r["kind"] == kind]) >= c["max_open_trades"]:
        return False, "max open trades (%d)" % c["max_open_trades"]
    if kind == "PAPER":
        return True, "paper"
    if not c["live_enabled"]:
        return False, "live trading is OFF (guard.json live_enabled=false) -- the user turns it on, never the bot"
    if stake > c["bankroll"] * c["max_risk_per_trade_pct"] + 1e-9:
        return False, "stake $%.2f > %.0f%% of $%.2f" % (stake, 100 * c["max_risk_per_trade_pct"], c["bankroll"])
    today = now.date().isoformat()
    lost = -min(0.0, ledger.realized("LIVE", since=today))
    if lost >= c["bankroll"] * c["daily_loss_limit_pct"]:
        halt("daily loss limit hit (-$%.2f)" % lost)
        return False, "daily loss limit"
    return True, "ok"


def halt(why, hours=None):
    c = cfg(); now = datetime.datetime.now(CT)
    until = (now + datetime.timedelta(hours=hours)) if hours else (now.replace(hour=23, minute=59, second=59))
    c["halted_until"] = until.isoformat(); json.dump(c, open(CFG, "w"), indent=1)
    try:
        from core.notify import send
        send("HALT", "%s -- trading stopped until %s" % (why, until.strftime("%m-%d %I:%M %p")), "high")
    except Exception:
        pass


if __name__ == "__main__":
    c = cfg(); print(json.dumps(c, indent=1))
    print("LIVE realized today: $%+.2f" % ledger.realized("LIVE", since=datetime.datetime.now(CT).date().isoformat()))
