# Trading desk

The second money engine next to `../sports betting`. Rules and history: `CLAUDE.md`.

```
pip install -r requirements.txt
python daily.py                          # status + combined bankroll
python daily.py paper --post             # run paper strategies once, post the summary
python -m strategies.pm_updown backfill btc 3   # test the Polymarket 5-min reversal on 3 days of real markets
python -m strategies.pm_updown loop btc  # paper-trade it every 5 minutes
python -m core.ledger                    # strategy records (PAPER vs LIVE)
python -m core.guard                     # risk limits; real money stays OFF until you set live_enabled in guard.json
python run_fomc_paper.py --wait          # the one strategy that passed (pre-FOMC drift), Alpaca paper
python run_arena.py --report             # forex paper arena scoreboard
```

Secrets: `.env` (Alpaca/OANDA paper keys) and `notify.json` (phone/Discord) are local only.
