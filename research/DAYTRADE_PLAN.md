# Day-trading research program (pre-registered 2026-10-08, before any of these were run)

Goal: find an intraday forex signal that survives retail costs. Each idea below comes from
published research or is the single most popular retail setup. Rules are fixed here and
are NOT changed after seeing results. Prior record: 27 strategies tested, 0 passed
(`results/sweep_log.csv`), so the bar is high on purpose.

## Data and honest mechanics (all tests)

- OANDA hourly candles, 13 pairs, Jan 2015 - Sep 2026 (`data/*_H1.csv`, bid prices).
- **Training period 2015-2021. Final exam 2022-now.**
- Decide on a bar's close, fill at the next bar's open (unless stated). Stop and target in
  the same hour: assume the stop.
- Cost per round trip = typical OANDA spread x 1.2 + 0.5 pip slippage (EUR/USD: 2.2 pips).
  The 1.2x reflects that our real 1-minute data showed spreads above the old assumption.
  Weekend-open trades pay 3x (spreads are widest then).
- Sizing: risk 1% of the account per trade (by stop distance, or by the typical move over
  the holding time when there is no stop), leverage capped at 20:1. Each test: $100 start.

## Pass rule (all tests)

Training period: average trade profitable after costs with t-stat >= 2.0.
Final exam: average trade still profitable after costs with t-stat >= 1.0.
Worst drop better than -25% in both periods. Anything else = FAIL, logged, not re-tuned.

## The six tests

**H1. Home-hours weakness** (Breedon & Ranaldo, "Intraday Patterns in FX Returns and Order
Flow", SNB WP 2011-04 / JMCB 2013). Currencies weaken in their own trading hours.
Sessions (UTC): Asia 00-06 (JPY, AUD, NZD), Europe 07-12 (EUR, GBP, CHF), America 13-19
(USD, CAD). For each pair and session where exactly one of its currencies is "home": sell
the home currency at the session's first bar open, buy back at the next session's first
bar open. No stop.

**H2. Month-end fix hedging** (Melvin & Prins, "Equity hedging and exchange rates at the
London 4pm fix", J. Financial Markets 2015). On the last trading day of the month, compare
SPY vs EFA month-to-date return (through the previous day's close). If US stocks did
better, foreign holders sell USD to rebalance hedges -> short USD; otherwise long USD.
USD pairs only (7). Enter 11:00 London time, exit at 16:00 London (the fix). No stop.

**H3. Round-number bounce** (Osler, NY Fed Staff Report 125: take-profit orders cluster at
round numbers -> reversals). 00-levels (1.1000, 1.1100 ... / 150.00, 151.00). Between
07-20 UTC, an hourly bar that reaches a 00-level from >= 5 pips away and CLOSES back on its
original side -> fade it at the next open. Stop 15 pips beyond the level, target 20 pips,
time stop 6 hours. One trade per level per day.

**H4. Round-number breakout** (Osler, NY Fed Staff Report 150: stop-loss orders cluster
just beyond round numbers -> cascades). Between 07-20 UTC, an hourly close >= 10 pips
through a 00-level that the previous close was on the other side of -> trade with the
break. Stop 10 pips back on the other side of the level, target 30 pips, time stop 8 hours.

**H5. London-open breakout** (most popular retail day-trade setup; no academic backing).
Asian range = high/low of 00:00-06:59 UTC bars; only if 15-60 pips wide. First hourly
close outside the range between 07:00-10:59 UTC -> enter at the next open with the break.
Stop at the far side of the range, target = one range-width, exit by 16:00 UTC.

**H6. Weekend gap fill.** If Sunday's first price is >= 15 pips from Friday's last close,
fade the gap at Sunday's first open. Target = Friday's close, stop = same distance the
other way, time stop 24 hours. Pays 3x cost.

Script: `run_daytrade_research.py`. Results: `results/daytrade_research.csv`.

---

# Round 2 (pre-registered 2026-10-09, before running). Round 1 result: all 6 FAILED.

**R1. Jobs-report drift (US Non-Farm Payrolls).** Data: OANDA 1-minute real bid/ask,
EUR/USD, GBP/USD, USD/JPY, Jan 2023-now. Release dates from the BLS rule (third Friday
after the week containing the 12th), 8:30am New York; a release counts only if the 8:30
minute's range is >= 3x the median range of 8:00-8:29 (catches delays like the 2025
shutdown). Signal: mid-price move from the 8:29 close to the 8:34 close. If >= 10 pips,
enter at the 8:35 open in that direction (real ask/bid), stop at the 8:29 close (the
pre-release price), exit at the 9:30 open. 1% risk, 50:1 cap. Only ~45 releases, so no
time split: PASS = average trade profitable after real costs with t-stat >= 2.0 across all
three pairs pooled, and profitable on at least 2 of 3 pairs.

**R2. Crypto intraday momentum** ("Intraday return predictability in the cryptocurrency
markets: momentum, reversal, or both", North American Journal of Economics and Finance
vol. 62, 2022, doi:10.1016/j.najef.2022.101733; and the Bitcoin intraday time-series
momentum literature). Data: Alpaca
30-minute bars, BTC/USD and ETH/USD, 2021-now. Signal: return from 00:00 to 00:30 UTC.
Trade 23:30-00:00 UTC the same day in that direction (up or down). Cost: Alpaca crypto
taker fee 0.25% per side (0.50% round trip); the no-fee result is reported only to show the
raw signal. Training 2021-2023, final exam 2024-now; same pass rule as round 1.
Note: down bets need a venue that allows shorting crypto; the test assumes one exists.

---

# Round 3 (pre-registered 2026-10-09, before running). Rounds 1-2: all 8 FAILED.

Lesson so far: intraday patterns make ~0 before costs and lose after. OANDA US "core"
pricing is not cheaper ($0.70 per 10k units each way = ~1.4 pips + ~0.2 raw spread, per
help.oanda.com/us/en/faqs/spreads-commission.htm), so the only lever left is trades that
aim for BIG moves, where a ~2-pip cost is a small slice.

**R3-1. Volatility breakout (Larry Williams-style day trade), 13 pairs, H1 2015-now.**
Day = 00:00-20:59 UTC. O = the 00:00 bar's open. R = previous UTC day's high-low.
Buy stop at O + 0.5R, sell stop at O - 0.5R; whichever hourly bar touches first triggers
the trade at that level (or at the bar's open if it gapped past). If both levels are
touched inside the same hour, skip the day (can't tell which came first). Stop-loss at O.
Exit at the 21:00 UTC open (before the daily rollover). One trade per pair per day.
Normal cost (spread x1.2 + 0.5 pip), 1% risk, 20:1 cap. Same pass rule as round 1
(training 2015-2021 t >= 2, final exam 2022-now t >= 1, worst drop better than -25%).

**R3-2. Pre-Fed-announcement drift (Lucca & Moench, "The Pre-FOMC Announcement Drift",
Journal of Finance 2015).** SPY, Alpaca 30-minute bars, scheduled FOMC meetings 2016-now
(dates from federalreserve.gov; the cancelled March 2020 meeting and emergency meetings
excluded). Buy at the 1:59pm ET price (13:30 bar close) the day before the announcement,
sell at the 1:59pm price on announcement day, just before the 2:00pm statement. Whole
$100, no leverage, 0.02% round-trip cost. Held overnight, so the day-trade limit does
not apply. ~85 events: PASS = profitable with t >= 2.0 over all events AND profitable in
both 2016-2020 and 2021-now.

---

# Round 4: seconds-scale scalping on QQQ (pre-registered 2026-10-09, before running)

Data: real recorded QQQ quotes from Alpaca, both the IEX book (what the free live feed
shows) and the full-market SIP book, sampled once per second, regular hours.
Replay rules (`run_replay_scalp.py`): the bot looks once a second; orders fill one second
later at the full-market ask (buys) / bid (sells); one position at a time; 1 share.
**Design days: Oct 6-8, 2026. Confirmation days (never looked at while designing):
Sep 28 - Oct 2 and Oct 5, 2026.** A seconds strategy passes only if it is profitable after
paying the spread on the design days AND on the confirmation days with t >= 2 there.

Ideas, all exit at +3c / -3c / 10 seconds unless stated:
- **S1 imbalance (IEX book)**: the live bot's rule. (bid size - ask size)/(sum) >= 0.6 buy, <= -0.6 short.
- **S2 imbalance (full-market book)**: same rule on the SIP book (needs paid real-time data live).
- **S3 queue depletion (made up, microstructure logic)**: the best ask's size drops to under
  25% of its average over the previous 5 seconds while the best bid size holds -> the ask is
  about to be eaten, buy; mirror for the bid -> short.
- **S4 tick momentum (made up)**: the full-market mid has ticked up in each of the last 3
  seconds -> buy; down 3 in a row -> short.
- **S5 spread-snap fade (made up)**: the spread widens to >= 3 cents, then snaps back to 1
  cent within 2 seconds with the mid moved >= 1 cent -> fade that move.

---

# Round 5 (queued 2026-10-09): classic chart patterns, detected by computer

Source of the list: the user's "Price Action Patterns" chart (20 patterns). Prior evidence:
Lo, Mamaysky & Wang (2000), "Foundations of Technical Analysis" (J. Finance) found small
incremental information in computer-detected patterns; Osler & Chang (1995, NY Fed Staff
Report 4), "Head and Shoulders: Not Just a Flaky Pattern", found H&S profitable in some
currencies, not others. Already tested and failed: H&S + neckline retest (Alex G rules),
range/rectangle breaks (London breakout, 1-min breakout, volatility breakout).
Still untested, to be defined exactly (swing highs/lows from a fixed lookback, trendlines
fit through them, entry only on a CLOSED candle beyond the breakout line, stop beyond the
pattern, target = pattern height) BEFORE any run: double top/bottom, triangles
(ascending / descending / symmetrical), wedges (rising / falling), flags and pennants,
cup and handle, rounding top/bottom, V-shape. Rules get written here first, same pass rule.

## Round 5 exact rules (pre-registered 2026-10-09, before running)

Data: hourly candles, 13 pairs, 2015-now. Training 2015-2021, final exam 2022-now.
Same costs, sizing (1% risk, 20:1 cap), fills (next bar open, stop-before-target) and pass
rule as round 1. ATR = 14-hour average true range at the signal bar.
Swing points: a swing high is a high that is the highest of the 3 bars on each side; it is
only KNOWN 3 bars later (no peeking). Same for swing lows. "Close beyond" = an hourly
candle CLOSES past the line (the chart's "wait for confirmation"). Entry at the next open.
A pattern is used once. Time stop 48 hours on every trade.

- **P1 Double top / bottom (#3, #4, #18).** Last two swing highs within 0.5 ATR of each
  other, 5-60 bars apart, with a swing low between them at least 1.5 ATR below the lower
  top (the neckline). Short on a close below the neckline within 30 bars of the second
  top. Stop 0.2 ATR above the higher top. Target = neckline minus pattern height. Mirror
  for double bottom (long).
- **P2 Ascending triangle (#15).** Last two swing highs within 0.5 ATR (flat top), last two
  swing lows rising by >= 0.5 ATR, all four within 60 bars. Long on a close above the higher
  top. Stop at the last swing low. Target = entry + (top - first low).
- **P3 Descending triangle (#8).** Mirror of P2: flat bottom, falling highs, short on a
  close below the lower bottom.
- **P4 Symmetrical triangle (#7).** Highs falling >= 0.5 ATR and lows rising >= 0.5 ATR
  within 60 bars. Trade the first close outside the lines (extended to the current bar),
  either direction. Stop at the opposite line's latest swing point. Target = widest
  height of the triangle.
- **P5 Rising wedge (#9) / falling wedge (#13).** Rising wedge: highs and lows both rising,
  lows rising faster (lines converging). Short on a close below the lower line. Stop at
  the last swing high. Target = wedge height at its start. Falling wedge: mirror, long.
- **P6 Flag / pennant (#10, #11, #14).** Pole: a move of >= 4 ATR within 10 bars. Then 5-20
  bars of consolidation whose range is <= 50% of the pole and that gives back <= 50% of
  it. Trade a close beyond the consolidation in the pole's direction. Stop at the other
  side of the consolidation. Target = pole length.
- **P7 Cup and handle (#19).** Two swing highs (rims) within 0.5 ATR, 20-120 bars apart,
  lowest low between them >= 3 ATR below the rims and in the middle half of the cup. Handle:
  after the right rim, a pullback of <= 1/3 of the cup depth. Long on a close above the
  higher rim. Stop at the handle low. Target = rim + cup depth.
- **P8 Rounding bottom / top (#5, #6).** Same as P7 without needing a handle: long on a
  close above the higher rim (bottom); mirror short for rounding top. Stop at the middle
  of the cup. Target = cup depth.
- **P9 V-shape (#20).** A drop of >= 4 ATR within 10 bars, then a recovery of >= 75% of it
  within the next 10 bars: long on that close. Stop at the V's low. Target = the drop's
  starting high. Mirror (inverted V) short.
Not retested: head & shoulders (#1, #2, #17, failed as Alex G rules) and rectangles
(#12, #16, failed as range breakouts).

---

# Round 6 (pre-registered 2026-10-09, before running). Rounds 1-5: 1 pass (pre-FOMC drift), 47 fails.

Lesson: chart shapes and short holds lose to costs; the only pass came from TIMING around a
scheduled event. Round 6 tests the best-documented timing effect in stocks.

**R6. Overnight drift** (Cliff, Cooper & Gulen 2008, "Return differences between trading
and non-trading hours: like night and day"; Lou, Polk & Skouras 2019, "A tug of war:
overnight versus intraday expected returns", J. Financial Economics). Most stock-index gains
arrive between the close and the next open. Trade: buy at the 3:59pm price (close of the
15:30 bar), sell at the next trading day's 9:30am open (open of the 9:30 bar). Every day.
Instruments: SPY and QQQ (Alpaca 30-minute bars, 2016-now). Cost 0.02% per round trip
(1-cent spread each way plus slippage, generous). Whole account, no leverage.
Benchmarks reported (not variants): buy-and-hold, and the opposite "daytime only" trade.
Training 2016-2021, final exam 2022-now. PASS (per instrument) = profitable after costs
with t >= 2.0 in training and t >= 1.0 in the final exam, worst drop better than -25%.

---

# Round 7 (pre-registered 2026-10-09, before running). Calendar effects; must beat ordinary days.

Data: SPY daily closes (Yahoo, dividend-adjusted), 1993-now. Training 1993-2015, final
exam 2016-now (the most recent decade is the exam). Cost 0.02% per round trip.
PASS = the window's average daily return beats all other days' average with an excess
t-stat >= 2.0 in training and >= 1.0 in the exam (two-sample test), AND the trade itself is
profitable after costs in both periods.
- **R7-1 Turn of the month** (Ariel 1987; McConnell & Xu 2008, "Equity Returns at the Turn
  of the Month", Financial Analysts Journal). Hold SPY from the close of the 2nd-to-last
  trading day of the month to the close of the 3rd trading day of the next month (4 days).
- **R7-2 Pre-holiday** (Ariel 1990; Lakonishok & Smidt 1988). Hold SPY for the single
  trading day before a US market holiday (close of the day before -> close of the
  pre-holiday day). Holidays = weekdays with no trading.
