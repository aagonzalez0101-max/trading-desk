# RESEARCH LOG -- daily cloud runs (US Central time, newest last)

## 2026-11-23 (Mon) -- run could not test anything: no data access

| Item | Result |
|---|---|
| PM-9 Polymarket "near-certain" carry (buy 95-99c outcomes 3 days before resolution) | **NOT RUN.** Rule written down and logged as PLANNED in `results/sweep_log.csv` before any data. |
| PM-8c Kalshi longshot (clean redo) | Skipped on purpose: local session owns it until 11/24. |
| PM-7 news-speed collector health | **PROBLEM, see below.** |

**Why nothing ran:** this cloud sandbox's network policy blocks every data host (Polymarket gamma/clob/data-api, Kalshi,
Pinnacle, Yahoo, Coinbase, Open-Meteo: HTTP 403 from the egress proxy). Without data a test can't be honest, so I wrote the
rule down and stopped. To unblock: allow those hosts in the environment's network settings (claude.ai/code -> environment ->
network access -> "Full" or a custom allowlist).

**Things that look broken**
1. **The speed collector has never run on GitHub.** `speed.yml` shows 0 runs. Its cron (`17 */6 * * *`) should have fired at
   ~06:17 and ~12:17 UTC today. The only data in `collected/speed/` is `2026-11-22.jsonl.gz` (141 price rows, 2 heartbeat-type
   rows) from the local test. If it never fires, PM-7 won't have its 3 weeks by mid-December. Fix: Actions tab -> speed-collector
   -> "Run workflow" once, and check Actions are enabled for the repo (scheduled runs can also lag 1+ hours).
2. **`phase2.yml` push runs 1-4 (11/22) all show "failure" with 0 jobs** -- those were from before the file was a clean
   schedule/dispatch workflow; the file parses fine now. Its first real scheduled run is today's 21:30 UTC pass: check that
   `results/phase2_equity.csv` appears after it (the file does not exist yet).

**Next in queue:** PM-9 (rule already logged), then K2 niche sports (CS2/tennis/table tennis/golf vs our models), K3 period totals.
