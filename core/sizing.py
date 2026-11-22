"""SIZING -- Kelly, capped by the guard (same math the betting desk uses for the model plan).
Binary bet (prediction-market share bought at price c, pays $1): edge comes from p (your win probability) vs c.
    kelly_binary(p, c, fee)  -> fraction of bankroll (full Kelly); use HALF of it, and never above guard's per-trade cap.
    stake(bankroll, p, c, fee=0, frac=0.5, cap=0.02)
"""


def kelly_binary(p, c, fee=0.0):
    cost = c + fee                       # $ per share incl. fee; pays $1 on a win
    if cost <= 0 or cost >= 1:
        return 0.0
    b = (1 - cost) / cost                # net odds
    f = (b * p - (1 - p)) / b
    return max(0.0, f)


def stake(bankroll, p, c, fee=0.0, frac=0.5, cap=0.02):
    return round(min(kelly_binary(p, c, fee) * frac, cap) * bankroll, 2)


def polymarket_taker_fee(price):
    """Polymarket crypto up/down taker fee per $1 share (measured 11/9): 0.07 * p * (1-p) -> ~1.75c at 50c. Makers pay 0."""
    return 0.07 * price * (1 - price)
