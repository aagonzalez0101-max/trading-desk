"""Virtual $100 account ("ledger") that every paper bot sizes its trades from.

The broker paper accounts hold $100k of fake money; we ignore that. Each bot keeps its
own ledger: it starts at $100, every real paper fill is recorded at its real price and
quantity, and new trades are sized from the ledger's value, so paper behaves exactly like
a real $100 account would.

Cycles: when a run blows up or the strategy changes, close the positions and reset.
The finished cycle's result is saved and a new one starts at $100.

  python -m bot.ledger etf            # show status
  python -m bot.ledger etf --reset "why"
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent.parent / "results"
NY = ZoneInfo("America/New_York")
EPS = 1e-9


class Ledger:
    def __init__(self, name: str, start: float = 100.0):
        self.path = OUT / f"ledger_{name}.json"
        if self.path.exists():
            self.s = json.loads(self.path.read_text())
        else:
            self.s = {"name": name, "start": start, "cycle": 1, "cycle_started": _now()[:10],
                      "cash": start, "positions": {}, "fills": [], "cycles": []}

    @property
    def start(self) -> float:
        return self.s["start"]

    @property
    def cash(self) -> float:
        return self.s["cash"]

    @property
    def positions(self) -> dict:
        return self.s["positions"]          # symbol -> {"qty": signed float, "avg": float}

    def qty(self, sym: str) -> float:
        return self.positions.get(sym, {}).get("qty", 0.0)

    def value(self, prices: dict) -> float:
        return self.cash + sum(p["qty"] * prices[s] for s, p in self.positions.items())

    def fill(self, sym: str, qty: float, price: float, tag: str, why: str = "", when: str | None = None) -> float:
        """Record a fill. qty > 0 buys, qty < 0 sells. Returns realized P&L."""
        pos = self.positions.get(sym, {"qty": 0.0, "avg": 0.0})
        q0, avg, realized = pos["qty"], pos["avg"], 0.0
        if abs(q0) < EPS or (q0 > 0) == (qty > 0):
            q = q0 + qty
            avg = (q0 * avg + qty * price) / q
        else:
            closed = min(abs(qty), abs(q0)) * (1 if q0 > 0 else -1)
            realized = closed * (price - avg)
            q = q0 + qty
            if abs(qty) > abs(q0) + EPS:   # flipped to the other side
                avg = price
        self.s["cash"] -= qty * price
        if abs(q) < EPS:
            self.positions.pop(sym, None)
        else:
            self.positions[sym] = {"qty": q, "avg": avg}
        self.s["fills"].append({"time": when or _now(), "cycle": self.s["cycle"], "tag": tag, "symbol": sym,
                                "qty": qty, "price": price, "realized": realized, "why": why})
        return realized

    def reset(self, end_value: float, reason: str):
        if self.positions:
            raise ValueError(f"Close these first: {', '.join(self.positions)}")
        self.s["cycles"].append({"cycle": self.s["cycle"], "started": self.s["cycle_started"], "ended": _now()[:10],
                                 "end_value": end_value, "return": end_value / self.start - 1, "reason": reason})
        self.s.update(cycle=self.s["cycle"] + 1, cycle_started=_now()[:10], cash=self.start)

    def save(self):
        self.path.write_text(json.dumps(self.s, indent=1))


def _now() -> str:
    return datetime.now(NY).isoformat(timespec="seconds")


if __name__ == "__main__":
    led = Ledger(sys.argv[1])
    if "--reset" in sys.argv:
        led.reset(led.cash, sys.argv[sys.argv.index("--reset") + 1] if len(sys.argv) > 3 else "manual reset")
        led.save()
    print(f"{led.s['name']}: cycle {led.s['cycle']} since {led.s['cycle_started']}, cash ${led.cash:.2f}")
    for s, p in led.positions.items():
        print(f"  {s}: {p['qty']:.6f} @ ${p['avg']:.2f} (cost ${p['qty'] * p['avg']:.2f})")
    for c in led.s["cycles"]:
        print(f"  past cycle {c['cycle']}: {c['started']} -> {c['ended']}, ended ${c['end_value']:.2f} ({c['return']:+.1%}): {c['reason']}")
