# TASK: build the Phase 2 paper arena + GitHub schedule (handed over 2026-11-22)

The user wants Phase 2 (slow swing/trend strategies) running NOW on paper in the background, automated on GitHub, checked and
graded on a schedule, while he works Phase 1 (PrizePicks) hands-on in the betting-desk session. No real money.

## Status at handoff
- Repo: private `aagonzalez0101-max/trading-desk` -- the user creates it on github.com (no gh CLI on this machine); the betting-desk
  session pushes the code once he says it exists. If `git remote -v` is empty, ask him whether it's created yet.
- Secrets he adds in GitHub (Settings -> Secrets -> Actions): ALPACA_API_KEY, ALPACA_SECRET_KEY (paper keys, same as .env),
  optional NOTIFY_JSON (contents of notify.json). Never commit .env or notify.json.

## Paper accounts (user 11/22, Alpaca allows 3)
- EXISTING account (keys = ALPACA_API_KEY/ALPACA_SECRET_KEY in .env): keeps the pre-FOMC drift test -- don't trade Phase 2 in it.
- NEW "Scar OGC" = Phase 2 Starter, $10,000 -> secrets ALPACA_KEY_10K / ALPACA_SECRET_10K.
- NEW "Full-Time Scale", $100,000 -> secrets ALPACA_KEY_100K / ALPACA_SECRET_100K. Same strategies, real fills at living size.
Each passing strategy gets a sleeve in BOTH new accounts (same weights, scaled). Neither syncs to a live balance.
- The OANDA practice token in .env has returned 401 since 2026-10-20: the forex arena has NOT been running. Ask the user for a
  new practice token only if he wants forex back (lowest priority).

## Build, in order
1. **Historical tests first (20+ years, free daily data, costs in, walk-forward by decade, `core/backtest.py` bar + must beat
   buy-and-hold on Sharpe AND worst drawdown).** Candidates (pre-declare each in results/sweep_log.csv):
   a. ETF time-series trend (3/6/12-month momentum, vol target ~10%, monthly rebalance) on SPY, QQQ, TLT, IEF, GLD, DBC, EFA, VNQ.
   b. Cross-asset trend (same rule, wider list incl. currency/commodity ETFs).
   c. Dual momentum (relative + absolute, monthly).
   d. Risk parity (inverse-vol weights, monthly).
   e. Benchmark: 100% SPY buy-and-hold, and 60/40.
   Only the ones that pass go into the arena. Record every result either way.
2. **Arena runner `run_phase2.py`**: one Alpaca PAPER account, each strategy gets a virtual sleeve (`bot/ledger.py`, $10,000 each,
   plus a $100,000 "full-time scale" shadow that's computed, not traded). Daily after the close: compute target weights, trade the
   sleeve difference in whole dollars (fractional shares), log every fill to `results/trades.jsonl` via `core/ledger.py`
   (PAPER/STRATEGY), mark-to-market each sleeve to `results/phase2_equity.csv`.
3. **GitHub Action `.github/workflows/phase2.yml`**: cron weekdays ~21:30 UTC (after the US close), python 3.12, `pip install -r
   requirements.txt`, write .env + notify.json from secrets, `python run_phase2.py`, commit `results/` back to the repo (bot user),
   weekly (Monday) `python daily.py --post`. Concurrency: one run at a time.
4. **Grading (built into run_phase2.py --review)**: monthly = health only (orders filled, fills near expected price, sleeve
   equity inside the backtest's normal band); QUARTERLY = the only time a strategy is cut/changed; a changed strategy is a NEW
   name with a reset record. Write each review to `results/phase2_reviews.md` and post a one-line summary to Discord.
5. Tell the user (and leave a note in results/ for the betting-desk session, which is his main advisor) what's running, what each
   sleeve backtested at, and what "normal" looks like so a bad month isn't mistaken for a broken strategy.

## The math the user already saw
Slow strategies (Sharpe 0.5-0.8) need ~6-16 years to PROVE on paper -> the proof is the 20-year walk-forward backtest; paper proves
execution. Phase 2 at ~10-15%/yr pays ~$1k/month only at ~$100-120k -> Phase 1 (props + prediction markets) builds the base;
PrizePicks surplus above ~$5k gets moved here by the user (`core/transfers.py`) once a sleeve has run cleanly on paper.
