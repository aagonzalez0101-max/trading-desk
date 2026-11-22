"""BACKTEST RULES -- the same bar the betting desk uses, so nothing fake gets near money.
  1. Pre-declare the rule. Changing it after looking = a NEW strategy (and the 53-tested tally goes up).
  2. Walk-forward: the rule must win in BOTH halves (found on the first, holds on the second) -- `halves()`.
  3. Costs IN: spread + fees + slippage per trade, always. A rule that only wins before costs is dead.
  4. Significance: t-stat and a permutation test; n >= 100 trades before calling anything real.
  5. Beat the do-nothing baseline (buy-and-hold, ordinary days), not just zero.
  6. Huge returns are a bug signal (look-ahead, a live price in the history, a survivorship list) -- investigate first.
    from core.backtest import report
    report("rule name", [net per trade ...], [timestamps ...])
"""
import math, random, statistics


def tstat(x):
    if len(x) < 2:
        return 0.0
    sd = statistics.stdev(x)
    return statistics.mean(x) / (sd / math.sqrt(len(x))) if sd else 0.0


def permutation_p(x, n=5000, seed=1):
    """sign-flip permutation: P(mean >= observed) if wins/losses were coin flips around 0."""
    if not x:
        return 1.0
    rnd = random.Random(seed); obs = statistics.mean(x); hit = 0
    for _ in range(n):
        if statistics.mean([v if rnd.random() < .5 else -v for v in x]) >= obs:
            hit += 1
    return hit / n


def halves(nets, keys):
    """split by time (keys sortable) into first / second half."""
    order = sorted(range(len(nets)), key=lambda i: keys[i]); mid = len(order) // 2
    return [nets[i] for i in order[:mid]], [nets[i] for i in order[mid:]]


def report(name, nets, keys, unit="$"):
    a, b = halves(nets, keys)
    line = lambda x: "n=%d net %s%+.2f avg %+.4f win %.0f%% t %+.2f" % (len(x), unit, sum(x), statistics.mean(x) if x else 0,
                                                                         100 * sum(v > 0 for v in x) / max(len(x), 1), tstat(x))
    p = permutation_p(nets)
    passed = len(nets) >= 100 and sum(a) > 0 and sum(b) > 0 and tstat(nets) >= 2 and p < .05
    print("%s\n  first half : %s\n  second half: %s\n  all        : %s  perm p=%.3f  -> %s" % (
        name, line(a), line(b), line(nets), p, "PASS" if passed else "FAIL"))
    return passed
