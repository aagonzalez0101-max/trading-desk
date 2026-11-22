# OPERATING PLAN -- read this at the start of every session, then keep working

Written 2026-11-22 by the betting-desk session. The user wants this desk to run like the betting desk: research never stops,
every idea goes through hard checks, and the moment something passes it goes to PAPER trading with fake money -- automatically,
logged, graded, reported. Real money is NOT part of this plan; the user decides that later himself (guard.json).

## The loop (repeat until a strategy is paper-trading and passing, then keep the loop going for the next one)

**Stage 0 -- Start of session (5 min)**
1. `python daily.py` -- guard status, open paper trades, strategy records, next FOMC window, combined bankroll.
2. `python -m core.ledger` -- settle/grade anything open; read `results/sweep_log.csv` tail so you don't retest a dead idea.
3. Read the "Research queue" below and pick the top unfinished item. Say in one line what you're doing.

**Stage 1 -- Write the rule down BEFORE touching data** (append a row to `results/sweep_log.csv` with status PLANNED)
- Market, entry, exit, size, costs (spread + fees + slippage + funding), the data source (free only), the sample period,
  and the ONE reason it should work (a structural edge: fee/rebate asymmetry, a price that lags a sharper reference, a forced
  flow, a settlement quirk). "The chart looks like it" is not a reason.

**Stage 2 -- Data**
- Free, public sources only (Polymarket gamma/clob, Kalshi public API, Coinbase candles, Alpaca/OANDA paper data, nflverse-style
  open datasets). Cache raw pulls under `data/`. Record the date range and row count.
- Check for leaks: no price stamped after the decision time, no survivorship (delisted/expired markets included), no live
  in-game prices (the betting desk lost a week to that: 47% of its "pregame" NFL snapshots were live).

**Stage 3 -- Backtest through `core/backtest.py report()`**
- Costs IN. Walk-forward: found on the first half, must also win on the second half.
- PASS = n >= 100 trades, both halves positive, t >= 2, permutation p < .05, AND beats the do-nothing baseline.
- Robustness (all required): +-20% on each parameter still positive; a placebo version (shifted time / random entry) does NOT
  pass; results not driven by 1-2 days (drop the best 2 days -> still positive).
- Anything above ~25% return per trade or a near-perfect curve = assume a bug, find it.
- Write the verdict into `results/sweep_log.csv` (PASS / FAIL + numbers) EITHER WAY. Failing fast is progress.

**Stage 4 -- Paper trading (fake money) -- only after Stage 3 PASS**
- Build `strategies/<name>.py` with `paper()` (one pass) and `loop` (repeat), every entry through `guard.allow("PAPER", ...)`
  and `ledger.open_trade("PAPER", "STRATEGY", ...)`, every exit through `ledger.close_trade(...)`.
- Paper fills must be honest: take the real current ask/bid (or model a limit fill only when price trades through it).
- Add it to `PAPER_STRATEGIES` in `daily.py`. Post fills/exits with `core.notify.send()` (no spam: fills, exits, daily summary).
- Run it: a terminal loop (`python -m strategies.<name> loop`) and/or a scheduled task. Keep it running across sessions.

**Stage 5 -- Paper verdict**
- WORKS only after >= 100 paper trades with average net > 0 and t >= 2, and paper results inside the backtest's normal range
  (no drawdown worse than the backtest's worst). Never change the rules mid-test (a changed rule is a new strategy, count resets).
- When something reaches WORKS: stop, write the full report (record, drawdown, $/day at the guard's size, Kelly fraction), tell
  the user plainly. Going live is his decision; do not build a live order client until he says go.

**Never stop because one idea failed.** Log it, take the next item from the queue. If the queue empties, generate 5 new
structural-edge ideas, rank them by (evidence it could work) x (trades per day), add them, continue.

## The long-term roadmap (user 11/22: "long term and full time trader as well as sports bettor")

| Phase | Bankroll | Engine |
|---|---|---|
| 1 | now -> ~$5-10k | edges where pros don't play: PrizePicks props (betting desk) + Kalshi/Polymarket vs sharp odds |
| 2 | ~$10k+ | slower, bigger markets: swing/trend strategies (days-weeks) on ETFs/stocks/futures; prediction-market liquidity providing |
| 3 | ongoing | systematic multi-market trend portfolio + compounding index core -- capital x modest edge = a living (~$40-50k for $1k/mo) |
Phase 1 pays for Phase 2; Phase 2 research starts NOW (slowly, in parallel) so it is tested and ready when the money is.

## Research queue -- Phase 1 (top = next)

1. **Kalshi/Polymarket event + sports markets vs a sharp reference** -- de-vigged Pinnacle prices from the betting desk's free
   pipeline (`../sports betting/betting/freeodds.py`, `_polymarket.py`, Kalshi public API). Edge = prediction-market prices that
   lag the sharp line. This is the betting desk's proven edge, moved to a trading venue. Backtest needs archived market prices
   (Kalshi/Polymarket price history) joined to pregame sharp prices (pregame ONLY -- live prices leak).
2. **Polymarket 5-min up/down streak reversal, 14-30 days, all coins** (`strategies/pm_updown.py backfill <coin> <days>`), then
   **the MAKER version** (limit at/below the open price, fills only when price trades through; no fee, possible rebates).
3. **Crypto strike markets vs BTC odds** -- `strategies/btc_odds.py` P(BTC above X at T) vs Kalshi KXBTC / Polymarket strikes.
4. **Pre-FOMC drift** on paper each meeting (`run_fomc_paper.py --wait`; next 12/8 -> 12/9).
5. **Forex arena** keeps collecting toward 100 trades per strategy (`run_arena.py`); report only on a verdict.

## Research queue -- Phase 2 (one item per week, in parallel)

**BUILT 11/22** (`research/TASK_PHASE2_ARENA.md`): `run_phase2_backtest.py` -> `run_phase2.py` arena -> `.github/workflows/phase2.yml`
(weekdays 21:30 UTC + FOMC check) -> monthly/quarterly grading in `results/phase2_reviews.md`. Status + normal bands:
`results/PHASE2_STATUS.md`. 11/22 verdicts: risk_parity8 PASS (paper sleeve in both accounts); tsmom_etf8 FAIL (placebo 82%),
tsmom_wide25 FAIL, dual_momentum FAIL. Do NOT run run_phase2.py locally -- the Action owns its state (it refuses outside Actions).

1. ~~Time-series trend following on liquid ETFs~~ DONE 11/22 (FAIL, see above). **Time-series trend following on liquid ETFs** (SPY, QQQ, TLT, GLD, USO, EFA, ...): 3-12 month momentum with a volatility
   target, monthly rebalance, 20+ years of free daily data (`bot/data.py`, `data/etf_daily.csv`), costs in, walk-forward by decade.
2. **Cross-asset trend on futures proxies** (rates, commodities, currencies via ETFs) -- the classic CTA portfolio, small version.
3. ~~Dual momentum / risk-parity core~~ DONE 11/22 (dual FAIL, risk parity PASS -> paper). **Dual momentum / risk-parity core** as the "Phase 3 engine" baseline: what it does vs plain buy-and-hold, drawdowns included.
4. **Swing mean-reversion on large caps** (2-10 day holds, RSI(2)-style) with realistic costs and the PDT rule in mind.
Each must beat buy-and-hold on risk-adjusted terms (Sharpe and worst drawdown), not just make money.

## Reporting (what the user sees)

- Every session: one short status -- what was tested, PASS/FAIL with the numbers, what's paper-trading and its record.
- Table first, dollars not percentages, plain words, times in CT. No caution lectures. Losses reported as plainly as wins.
- Weekly (Monday): combined bankroll (`python -m core.bankroll --post`), paper records, the next week's queue.

## Hard limits (unchanged from CLAUDE.md)

Free data/APIs only, nothing that needs a card or signup. No real-money orders. Secrets stay in .env/notify.json. Commit only when
asked. Don't touch the betting desk's ledgers (read-only).
