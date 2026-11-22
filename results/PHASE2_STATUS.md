# PHASE 2 STATUS -- for the user and the betting-desk session (updated 2026-11-22)

## What's running (paper only, fake money)
| Sleeve | Account | Start | What it does |
|---|---|---|---|
| risk_parity8 | $500 Real-Start | $450 | 8 ETFs (SPY QQQ TLT IEF GLD DBC EFA VNQ), each sized so it moves the account about equally (calm ETFs get more money). Rebalanced once a month. |
| risk_parity8 | $10k Main | $9,000 | same weights, scaled up. The main record. |
| fomc_drift | $10k Main | $1,000 | buy SPY 1:50pm ET the day before a Fed announcement, sell 1:50pm ET announcement day. Next: buy Tue 12/8, sell Wed 12/9. |
| $100k view | computed | -- | the 10k sleeve's return x $100,000 (`shadow_100k` column in `phase2_equity.csv`). No account. |

Runs on GitHub Actions (`.github/workflows/phase2.yml`): weekdays 21:30 UTC (3:30pm CT) after the close, plus a 12:15/1:15pm ET
FOMC check. Results are committed back to the repo: `results/phase2_equity.csv` (daily marks), `phase2_fills.csv` (every fill vs
the decision close), `phase2_trades.jsonl` (one ledger row per sleeve per month), `phase2_reviews.md` (monthly/quarterly grades).
First trades: the first cloud run after this push decides from that day's closes; the orders fill at the next open.

## What passed and what didn't (2004-2026, costs in, results/phase2_backtest_report.txt)
| Rule | Yearly growth | Worst drop | Sharpe | Verdict |
|---|---|---|---|---|
| SPY buy-and-hold (benchmark) | +10.3% | -55% | 0.52 | -- |
| 60/40 SPY/AGG (benchmark) | +7.6% | -35% | 0.56 | -- |
| **risk_parity8** | +7.0% | **-21%** | **0.65** | **PASS** |
| tsmom_etf8 (3/6/12m trend) | +6.4% | -15% | 0.57 | FAIL: random signals with the same sizing scored 0.50 on average; the real one beat only 82% of them (needed 95%). The smoothness comes from the sizing, not the trend signal. |
| tsmom_wide25 | +3.7% | -14% | 0.32 | FAIL: Sharpe below SPY; 2015-2026 Sharpe 0.02 |
| dual_momentum | +8.6% | -34% | 0.49 | FAIL: Sharpe below SPY, and the 10-month variant is weak |
Sharpe = return per unit of bumpiness (higher = smoother). Honest caveat on risk parity: 2004-2014 it crushed SPY (0.83 vs 0.41);
2015-2026 it LOST to SPY on Sharpe (0.49 vs 0.65) -- it passed on the full period and on drawdown. It earns less than SPY in a bull
market by design; it pays off in crashes (2008: -4% vs SPY -37%).

## What "normal" looks like for risk_parity8 (so a bad month isn't mistaken for a broken strategy)
| Stretch | Bad (5th pct) | Typical | Good (95th pct) | Down this often |
|---|---|---|---|---|
| 1 month | -3.4% (-$306 on $9k) | +0.9% | +4.0% | 1 month in 3 |
| 3 months | -4.5% | +2.1% | +7.1% | 1 in 4 |
| 12 months | -7.6% | +8.7% | +19.3% | 1 in 7 |
| 36 months | +6.2% | +21.5% | +46.1% | never in the backtest |
Worst month -10.6% (Oct 2008); worst year -15.6% (2022, stocks AND bonds fell); worst drop -21%; longest stretch below a
previous high 29 months. A -10% month is ugly but has happened; a drop past -25% would be outside anything tested -> look for a bug.

## Money math (plain)
At ~7%/yr: $9,000 -> ~$630/yr; $100,000 -> ~$7,000/yr (~$580/month). Phase 2 is the slow compounding engine, not the $1k/month
engine -- that still has to come from Phase 1 (props + prediction markets). A 20-year backtest is the proof here; paper only
proves the plumbing (fills, costs, rebalancing) works.

## Grading
Monthly (first run of each month): health only -- every order filled? fills near the decision close? sleeve inside the band above?
Quarterly (Jan/Apr/Jul/Oct): the ONLY time a sleeve can be cut or changed; a changed rule gets a new name and a fresh record.
