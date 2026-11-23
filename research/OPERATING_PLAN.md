# OPERATING PLAN -- read this at the start of every session, then keep working

Written 2026-11-22 by the betting-desk session. The user wants this desk to run like the betting desk: research never stops,
every idea goes through hard checks, and the moment something passes it goes to PAPER trading with fake money -- automatically,
logged, graded, reported. Real money is NOT part of this plan; the user decides that later himself (guard.json).

**Cloud research agent (11/22):** a daily claude.ai routine (7am CT, https://claude.ai/code/routines/trig_01LeR5Rz1ieGchg2dwRggPHW) runs this loop and logs to `results/RESEARCH_LOG.md`.

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

0. **TOP PRIORITY (user 11/22 night): the AGGRESSIVE prediction-market bot -- Polymarket + Kalshi, $20 each, ML + alt
   props only, fully automated, zero user input.** PrizePicks is untouched (betting desk). Build:
   a. Scanner every few minutes: Polymarket + Kalshi game ML, spreads/alt lines and player-prop markets vs Pinnacle de-vigged fair
      (free: ../sports betting/_polymarket.py, betting/freeodds.py, Kalshi public API). VALUE = market price beats fair by >= 3%
      AFTER fees + spread. No value -> no bet (the user said "only whenever the value is there").
   a2. ALT-LINE LADDER (user 11/22): for every prop, compute our fair P at EVERY listed line (counting stats -> negative-binomial /
      Poisson from the player's per-minute rate x projected minutes; yards -> empirical distribution), compare to each line's price,
      and take ONLY the single max-EV line if EV >= 3% after fees. Close calls usually = no bet: buying a line down costs more than
      it's worth on most ladders (alt lines carry extra cut). Never pick a line for "safety" -- pick it for EV.
   a3. PRE-BET CONTEXT CHECK (user 11/22): before any player-prop or ML bet, check ESPN injuries -- the player's own status
      (skip OUT/doubtful/questionable/day-to-day) and NEW teammate absences (a rotation teammate OUT who played the last game breaks
      UNDERS and boosts usage; skip unders then). Same logic as ../sports betting/_guardian.py. Log the check result with the bet.
   a4. AUDIT TRAIL: every bet row logs price, fair price, sources/books, edge, stake, and the context-check result, so the
      betting-desk session can audit each bet afterwards and flag mistakes; fixes it writes into this plan get built next.
   a5. MODEL-LEG PRICE LOG (betting desk 11/22): every night, for each leg in ../sports betting/prop_model_paper.jsonl (the NBA/NHL
      model's top 10), log the REAL Kalshi/Polymarket price at the main line AND every alt line listed. Betting-desk backtest with
      made-up prices: main line +17% (62% hit), 1-point alt +12% top-3, 2+ points ~break-even; top-3 alt parlays +20-66% on n=15-21.
      Two weeks of real prices decide whether model legs go to Kalshi (main line first, alt max 1 point, parlays only if they hold).
   **11/23 EVIDENCE for (a): PM-10 FAIL** (`run_pm_props.py`): Kalshi player props sit a median 1.2c from Pinnacle fair (14,030 pregame pairs,
   spread 2c); only 0.25% clear 3c after fees, and those 31 lost. With PM-1/PM-2 (game lines) that means a Pinnacle-vs-exchange 3% scanner
   would basically never fire on Kalshi. Still untested: Polymarket props (PM-11, next) and -- the real candidate -- the betting desk's own
   model vs Kalshi prices (a5). Build a5's price log FIRST; the scanner only matters if a5 or PM-11 shows an edge.
   b. Sizing for this $40 micro-bankroll (user wants it aggressive): half-Kelly, cap 5% of the venue's bankroll per bet, -15% daily
      stop, HARD FLOOR: if a venue drops to $10, stop that venue and report. Set via guard.json for these venues only.
   c. Runs PAPER and LIVE side by side from day 1: paper logs every signal; LIVE only after the user moves the money and puts the
      Kalshi API key / Polymarket wallet key in .env HIMSELF and sets live_enabled. Never handle his keys.
   d. Report weekly: bets, hit rate, CLV (did the price move toward us after entry), $ per venue. Scale = PrizePicks surplus via
      core/transfers.py, only when the live record beats the bar (100+ bets, t >= 2, positive CLV).
1. ~~Kalshi game moneylines vs Pinnacle~~ **FAIL 11/22** (`run_pm_sharp_study.py`: Kalshi ask within ~1c of Pinnacle fair, 11,080 quotes; after fees 0.15% of quotes clear 3c). PM-2 Polymarket game moneylines vs Pinnacle **FAIL 11/22** (`run_pm_poly_study.py`: 7,810 pairs, 99th pct gap +2.1c, 0 trades). Pregame sports moneylines on BOTH exchanges sit on the sharp line; only a speed (news) edge could remain.
   **Kalshi/Polymarket event + sports markets vs a sharp reference** -- de-vigged Pinnacle prices from the betting desk's free
   pipeline (`../sports betting/betting/freeodds.py`, `_polymarket.py`, Kalshi public API). Edge = prediction-market prices that
   lag the sharp line. This is the betting desk's proven edge, moved to a trading venue. Backtest needs archived market prices
   (Kalshi/Polymarket price history) joined to pregame sharp prices (pregame ONLY -- live prices leak).
2. ~~Up/down reversal, 4 coins x 14 days, maker + taker~~ **FAIL 11/22** (`run_pm_updown_maker.py`): maker -5.4c/share (filled 43.6% win vs unfilled 98.1% -- adverse selection); taker +1.7c but first half t 0.30 and dead after a half-cent of spread. Closed unless new evidence.
   **Polymarket 5-min up/down streak reversal, 14-30 days, all coins** (`strategies/pm_updown.py backfill <coin> <days>`), then
   **the MAKER version** (limit at/below the open price, fills only when price trades through; no fee, possible rebates).
3. ~~Crypto strike markets vs BTC odds~~ **FAIL 11/22** (`run_pm_btc_ladder.py`: 780 trades, -3.2c each; model expected 83% wins, got 73% -- Kalshi's makers out-price our vol model).
   **Crypto strike markets vs BTC odds** -- `strategies/btc_odds.py` P(BTC above X at T) vs Kalshi KXBTC / Polymarket strikes.
4. **Pre-FOMC drift** on paper each meeting (`run_fomc_paper.py --wait`; next 12/8 -> 12/9).
5. **Forex arena** keeps collecting toward 100 trades per strategy (`run_arena.py`); report only on a verdict.

### New ideas 11/22 (queue #1-3 all failed; ranked by evidence-it-could-work x trades/day, all free data)
6. ~~PM-5~~ **FAIL 11/22** (54 fills, +$0.15; filled 42.6% won vs 44.8% expected = adverse selection eats the 2c). **PM-5 Polymarket sports MAKER vs Pinnacle fair** -- rest a bid 2c under Pinnacle's de-vigged price, no fee + 15% rebate. Testable NOW on the
   208 cached games with data-api v2 trades (trade-through fills). Known risk: adverse selection (PM-3 lesson: 43.6% vs 98.1%).
7. ~~Kalshi daily highs vs forecast~~ **FAIL 11/22** (`run_pm_weather.py`: 728 trades -3.6c; market Brier 0.084 beats the day-old forecast's 0.128).
   **Kalshi daily-high temperature markets vs free forecasts** (Open-Meteo historical-forecast API, NWS) -- retail-priced, many markets/day, the
   reference is a professional model nobody pays for. Needs a forecast archive (Open-Meteo has one, free, no key).
8. **COLLECTING on GitHub since 11/22** (`.github/workflows/speed.yml`: `collect_speed.py run 335` every 6h, 2-min passes, deduped gzip -> collected/speed/, PM-7 pre-declared). User 11/22: everything runs on GitHub so it works with the PC off. Test at >= 100 signals (~mid-Dec).
   **News-speed collector**: Pinnacle + Kalshi/Polymarket game prices every few minutes, forward; measure how long exchanges lag a >=3c sharp move.
   The archive tested (5-min-fresh) shows no lag on average; the edge, if any, is in the first minutes after news. Collect 3-4 weeks, then test.
9. ~~P2-F RSI(2) ETFs~~ **FAIL as a portfolio 11/22** (`run_phase2_rsi2.py`): per trade +0.21%, t 5.6, survives post-2009 and the placebo; but 14 slots = +3%/yr, Sharpe 0.30 < SPY. P2-G overlay on the risk-parity core: back-of-envelope says NO -- funding a dip from the core costs a 2nd round trip (0.2%) + the core's own ~0.14%/5 days, > the dip's +0.21%; funded only from the idle 10% buffer it adds ~+0.5%/yr of the account. LOW priority.
   **ETF RSI(2) swing mean-reversion** (Phase 2 queue #4, on ETFs so no survivorship) -- published 2008, so the second half doubles as a decay test.
11. **PM-8 longshot bias on Kalshi** (all categories): do 1-10c YES contracts win less often than their price? If so, BUY NO on them. The classic
    favorite-longshot bias; plentiful settled markets + candles, free. PM-8 ran 11/22 but its sample used LIFETIME volume (look-ahead; verdict invalid). **PM-8c FAIL 11/23** (`run_pm_longshot_clean.py`): the longshot premium is real (3-6c YES wins 2.8%) but ~1-3c, eaten by spread+fee on the NO side; NO <=10c -$9.47 t -1.89, YES 5-20c -$25.59 t -3.49. Lesson for every test: filter by liquidity measured BEFORE the decision, never by lifetime volume.
12. **PM-9 'near-certain' carry on Polymarket**: buy 95-99c outcomes days before resolution; does the hit rate beat the price after the rare blowups?
10. Polymarket 5-min up/down late-window lag vs Coinbase (needs second-level data, bots compete) -- lowest.

## Kalshi niche queue (betting desk 11/23, after a full scan of 8,000 open events)
- K1 (running on the betting desk): NBA player props vs the prop model -> `../sports betting/_kalshi_paper.py`, kalshi_paper.jsonl.
- K2: NICHE SPORTS WE ALREADY MODEL -- Kalshi CS2 (147 series), tennis (145), table tennis (13), golf (128). Match each open market to
  the betting desk's models (cs2_paper.jsonl lowers w/ edge, `_tennis_pp.py` Pinnacle-fitted probs, `_tabletennis.py` bo5 under rates,
  `_golf_holes.py`), paper-bet $1 when model p beats price+fee by 3+ pts. Thin markets = where mispricing lives.
- K3: NBA/NHL quarter & period totals vs Pinnacle quarter lines -- PP period props lean UNDER (2H unders 55.8%, filtered 59.7%); test
  whether Kalshi quarter totals carry the same tilt.
- K4/K5 = PM-8 longshot bias (buy NO on 3-10c longshots, huge election volume) and PM-9 near-certain carry.
- Skip: Oscars/Coachella/GTA/cabinet (insider-driven), game ML/spreads, BTC ladders, temps (all tested/failed or no data edge).

## Research queue -- Phase 2 (one item per week, in parallel)

**BUILT 11/22** (`research/TASK_PHASE2_ARENA.md`): `run_phase2_backtest.py` -> `run_phase2.py` arena -> `.github/workflows/phase2.yml`
(weekdays 21:30 UTC + FOMC check) -> monthly/quarterly grading in `results/phase2_reviews.md`. Status + normal bands:
`results/PHASE2_STATUS.md`. 11/22 verdicts: risk_parity8 PASS (paper sleeve in both accounts); tsmom_etf8 FAIL (placebo 82%),
tsmom_wide25 FAIL, dual_momentum FAIL. Do NOT run run_phase2.py locally -- the Action owns its state (it refuses outside Actions).

1. ~~Time-series trend following on liquid ETFs~~ DONE 11/22 (FAIL, see above). **Time-series trend following on liquid ETFs** (SPY, QQQ, TLT, GLD, USO, EFA, ...): 3-12 month momentum with a volatility
   target, monthly rebalance, 20+ years of free daily data (`bot/data.py`, `data/etf_daily.csv`), costs in, walk-forward by decade.
2. ~~Cross-asset trend~~ DONE 11/22 = tsmom_wide25 (25 ETFs incl. currencies/commodities) FAIL. **Cross-asset trend on futures proxies** (rates, commodities, currencies via ETFs) -- the classic CTA portfolio, small version.
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
