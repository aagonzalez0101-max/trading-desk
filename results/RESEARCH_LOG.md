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

## 2026-11-24 (Tue, 7am CT run) -- nothing testable: cloud network still blocked

| Item | Result |
|---|---|
| Next queue item (K3 NBA/NHL period totals vs Pinnacle; K2 niche sports is low-prior and needs a forward Pinnacle archive) | **NOT RUN.** Every data host (Polymarket, Kalshi, Yahoo) still returns no connection from this sandbox, same as 11/23. No PLANNED row added (nothing to test it on; no point cluttering the sweep log). |
| PM-7 collector health | **Working.** speed.yml has been committing: 338 distinct 2-min passes, 11/22 20:17 UTC -> 11/24 07:46 UTC. Gaps over 30 min: 11/23 20:33 -> 02:12 UTC (the known 11/23 18:25-02:12 run whose data was lost to a rebase conflict, fixed in commit 9456c4c) and the first-day gap before the first Actions run. Latest data is 11/24 07:46 UTC, so watch that the next 6-hour runs keep landing. Needs ~3 weeks of clean data, so the PM-7 test is still ~mid-December (earliest ~12/15). |
| Phase 2 sleeve (`phase2_equity.csv`) | Last row 11/23 (the first run, both accounts flat at start equity). The 11/24 21:30 UTC pass is still ahead of this run -- check it appears tomorrow. |
| props scanner | Committing every ~10 min ("props scan" commits through 11/24 09:37 UTC). |

**Fix needed to get research moving:** allow the data hosts (gamma-api.polymarket.com, clob.polymarket.com, data-api.polymarket.com,
api.elections.kalshi.com, guest.api.arcadia.pinnacle.com, query1.finance.yahoo.com, api.coinbase.com, open-meteo.com) in the
environment's network settings (claude.ai/code -> environment -> network access). Until then this routine can only do health checks.
