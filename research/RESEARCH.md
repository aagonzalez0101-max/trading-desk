# What actually makes money trading — research notes (2026-09-25)

Each claim below was confirmed with 2+ independent sources.

## 1. Most discretionary / day traders lose
- **Brazil (Chague, De-Losso, Giovannetti 2019):** everyone who started day trading
  futures 2013–15. Of those who kept going 300+ days, **97% lost money**; ~1% earned more
  than minimum wage. No evidence traders improved with practice.
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101
- **Taiwan (Barber, Lee, Liu, Odean):** 3.7 billion trades, 1992–2006. **80%+ of day
  traders lose in a typical 6 months; <1% reliably profit** after fees.
  https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trading%20and%20Learning%20110217.pdf
- **Broker disclosures (2026):** 54–67% of US forex accounts lose; EU/UK average 71%.
  https://brokerrank.net/research/retail-loss-rates

## 2. What has real evidence: trend following
- **Moskowitz, Ooi, Pedersen (2012):** past 1–12 month returns predict future returns in
  all 58 futures/forwards tested, **including currencies**, over 25+ years.
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463
- **Hurst, Ooi, Pedersen (2017):** trend following was **positive in every decade since
  1880** and did well in 8 of the 10 worst stock/bond crises.
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026
- **Caveat:** it has long flat/losing stretches. SG Trend Index: −3.3% in 2023, ~+2% in
  2024. It's slow, diversified, and boring — not "hella money" fast.
  https://content.sgmarkets.com/CTA_UPDATE_KEEPING_UP_WITH_THE_TRENDFOLLOWERS_2025

## 3. The #1 trap when building a bot: overfitting
- **Bailey, Borwein, López de Prado (2014):** try enough strategy variations and one will
  look amazing on past data by luck. The more you try, the more likely the "winner" is fake.
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659
- This is exactly the "Claude tested 9,000 strategies" YouTube genre.
- **Fix:** decide rules first, test on data the rules never saw (out-of-sample), keep
  the number of variations small, include spreads/fees.

## 4. Reading list (best-regarded for our situation)
1. **Robert Carver — *Leveraged Trading* (2019).** Written for small retail FX/CFD
   accounts; simple "Starter System" trend rule with proper position sizing. Most relevant
   book for us. Free blog: https://qoppac.blogspot.com
2. **Ernest Chan — *Quantitative Trading* (2nd ed. 2021).** How a solo person sets up
   a backtest → live algo business.
3. **Rishi Narang — *Inside the Black Box*.** Math-free overview of how pro quants work.
4. **Carver — *Systematic Trading*.** Deeper follow-up once #1 makes sense.
   (QuantStart's beginner list: https://www.quantstart.com/articles/Top-5-Essential-Beginner-Books-for-Algorithmic-Trading/)

## 5. YouTube / online worth watching
- **Trading Rush** — tests popular YouTube strategies 100× each; most fail.
  https://tradingrush.net/trading-strategies-tested-100-times/
- **Part Time Larry** — Python trading bots, broker APIs, backtesting.
  https://www.youtube.com/c/parttimelarry
- **Robot Wealth (Kris Longmore)** — engineer-turned-trader; honest, evidence-first
  systematic trading for part-timers. Free Substack: https://edgealchemy.robotwealth.com/
- **Better System Trader podcast** — interviews with systematic traders.

## 6. Broker fit: OANDA US
- No minimum deposit, trades as small as **1 unit** (so a $10 account can size correctly),
  50:1 max leverage on majors, CFTC/NFA regulated.
  https://www.oanda.com/us-en/trading/spreads-margin/ ·
  https://help.oanda.com/us/en/faqs/minimum-deposit-requirement.htm

## Takeaway for the bot
Backtest two strategies side by side, same data, same costs, out-of-sample:
1. **AlexG Set & Forget** (see `alexg/STRATEGY.md`)
2. **Carver-style trend-following baseline** (the one with 100+ years of evidence)

If AlexG's rules can't beat a simple trend rule after costs, we use the trend rule.
