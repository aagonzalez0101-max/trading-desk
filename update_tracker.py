"""Rebuild results/trading_tracker.xlsx and the dashboard from the $100 ledger (bot/ledger.py).

  python update_tracker.py

Read-only: never sends orders. Safe to run any time (close the file in Excel first).
All money figures are the virtual $100 account, not Alpaca's $100k balance.
Each run also appends today's ledger value to results/equity_history.csv, so the Equity
History tab grows by one row per day you run it.
"""
import csv
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from bot.alpaca import Paper, have_keys
from bot.journal import WEEKLY as P
from bot.ledger import Ledger
from bot.weekly_live import weekly_bars
from run_alpaca_paper import NY, last_closed_friday, prices
from bot.data import OUT

XLSX = OUT / "trading_tracker.xlsx"
HTML = OUT / "dashboard.html"
TEMPLATE = Path(__file__).resolve().parent / "bot" / "dashboard_template.html"
EQ_HIST = OUT / "equity_history.csv"
PLAN_SIZE = 100.00  # real-money amount the user plans to start with (= ledger start)

FONT = "Arial"
HEAD = PatternFill("solid", fgColor="1F3864")
INPUT = Font(name=FONT, color="0000FF")
GOOD = PatternFill("solid", fgColor="C6EFCE")
BAD = PatternFill("solid", fgColor="FFC7CE")
USD = '$#,##0.00;($#,##0.00);"-"'
PCT = '0.00%;(0.00%);"-"'


def header(ws, cols, widths):
    ws.append(cols)
    for i, w in enumerate(widths, 1):
        c = ws.cell(row=1, column=i)
        c.font = Font(name=FONT, bold=True, color="FFFFFF")
        c.fill = HEAD
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def fonts(ws):
    for row in ws.iter_rows():
        for c in row:
            if c.font.name != FONT:
                c.font = Font(name=FONT, bold=c.font.bold, color=c.font.color, size=c.font.size)


def snapshot(led, px_now):
    """Append/replace today's ledger value row."""
    rows = list(csv.DictReader(EQ_HIST.open())) if EQ_HIST.exists() else []
    today = datetime.now(NY).strftime("%Y-%m-%d")
    if px_now is not None:
        rows = [r for r in rows if r["date"] != today] + [
            {"date": today, "equity": round(led.value(px_now), 4), "cash": round(led.cash, 4)}]
        with EQ_HIST.open("w", newline="") as f:
            w = csv.DictWriter(f, ["date", "equity", "cash"])
            w.writeheader()
            w.writerows(rows)
    return rows


def signals():
    friday = last_closed_friday(datetime.now(NY))
    b = weekly_bars(prices(friday), friday)
    t = b.index[-1]
    sma, ema = b.rolling(P.trend_len).mean(), b.ewm(span=P.ema_len, adjust=False).mean()
    mom = b.pct_change(P.mom_len)
    dip = (b <= ema).rolling(P.dip_window).max().shift(1).fillna(0).astype(bool)
    return t, [(a, b.at[t, a], b[a].iloc[-2], sma.at[t, a], mom.at[t, a], ema.at[t, a], bool(dip.at[t, a]))
               for a in b.columns]


def build(api):
    wb = Workbook()
    led = Ledger("etf")
    broker = api.positions() if api else {}
    px_now = {s: float(broker[s]["current_price"]) if s in broker else p["avg"] for s, p in led.positions.items()}
    eq_rows = snapshot(led, px_now if api else None)
    tags = {f["symbol"]: f["tag"] for f in led.s["fills"] if f["cycle"] == led.s["cycle"]}
    positions = {s: {"qty": p["qty"], "avg": p["avg"], "price": px_now[s], "type": tags.get(s, "STRATEGY")}
                 for s, p in led.positions.items()}
    fills = led.s["fills"]

    # ---------- Dashboard ----------
    ws = wb.active
    ws.title = "Dashboard"
    ws["A1"] = "Trading Bot Tracker: $100 paper account"
    ws["A1"].font = Font(name=FONT, bold=True, size=14)
    ws["A2"] = f"Last updated {datetime.now(NY):%Y-%m-%d %H:%M} ET by update_tracker.py"
    ws["A2"].font = Font(name=FONT, italic=True, color="808080")
    n_eq = len(eq_rows) + 1
    rows = [
        ("Cycle start value", led.start, USD),
        ("Current equity", f"=IFERROR(INDEX('Equity History'!B2:B{max(n_eq, 2)},COUNT('Equity History'!B2:B{max(n_eq, 2)})),B4)", USD),
        ("Total P&L", "=B5-B4", USD),
        ("Total return", "=IFERROR(B6/B4,0)", PCT),
        ("Cash", f"=IFERROR(INDEX('Equity History'!C2:C{max(n_eq, 2)},COUNT('Equity History'!C2:C{max(n_eq, 2)})),B4)", USD),
        ("Open positions", "=COUNTA(Positions!A2:A100)", "0"),
        ("Unrealized P&L (open positions)", "=SUM(Positions!G2:G100)", USD),
        (None, None, None),
        ("Orders logged: strategy", '=COUNTIF(\'Trade Log\'!B2:B1000,"STRATEGY")', "0"),
        ("Orders logged: manual", '=COUNTIF(\'Trade Log\'!B2:B1000,"MANUAL")', "0"),
        ("Orders logged: test", '=COUNTIF(\'Trade Log\'!B2:B1000,"TEST")', "0"),
        ("Signals passing this week", '=COUNTIF(\'Weekly Signals\'!L2:L20,TRUE)', "0"),
    ]
    for i, (k, v, fmt) in enumerate(rows, start=4):
        if k is None:
            continue
        ws.cell(row=i, column=1, value=k).font = Font(name=FONT, bold=True)
        c = ws.cell(row=i, column=2, value=v)
        c.number_format = fmt
    ws["A16"], ws["B16"] = "Cycle", f"#{led.s['cycle']} since {led.s['cycle_started']}"
    ws["A17"], ws["B17"] = "Finished cycles", "=COUNTA(Cycles!A2:A100)"
    for k in ("A16", "A17"):
        ws[k].font = Font(name=FONT, bold=True)
    ws["A18"] = "Notes"
    ws["A18"].font = Font(name=FONT, bold=True)
    notes = [
        "Every number here is the virtual $100 account the bots size from (results/ledger_etf.json), not Alpaca's $100k.",
        "STRATEGY = picked by the rules. MANUAL = your off-rules EFA position. TEST = plumbing test (bought and sold back).",
        "Judge the strategy only on STRATEGY trades. Weeks with no trade are normal.",
        "Refresh: python update_tracker.py (also runs automatically after weekly_paper.bat).",
        "This file is rebuilt on every refresh; notes typed into it will be overwritten.",
    ]
    for i, n in enumerate(notes, start=19):
        ws.cell(row=i, column=1, value=n)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 18

    # ---------- Positions ----------
    wp = wb.create_sheet("Positions")
    header(wp, ["Symbol", "Qty", "Avg entry ($)", "Current price ($)", "Cost basis ($)", "Market value ($)",
                "Unrealized P&L ($)", "Unrealized %", "Type"], [10, 12, 14, 16, 16, 16, 18, 14, 12])
    for r, (sym, p) in enumerate(sorted(positions.items()), start=2):
        wp.append([sym, p["qty"], p["avg"], p["price"],
                   f"=B{r}*C{r}", f"=B{r}*D{r}", f"=F{r}-E{r}", f"=IFERROR(G{r}/E{r},0)", p["type"]])
        for col in "CDEFG":
            wp[f"{col}{r}"].number_format = USD
        wp[f"H{r}"].number_format = PCT
        wp[f"B{r}"].number_format = "0.000000"
    if not positions:
        wp["K1"] = "No open positions right now."

    # ---------- Trade Log ----------
    wt = wb.create_sheet("Trade Log")
    header(wt, ["Time (ET)", "Type", "Action", "Symbol", "Qty", "Fill price ($)", "Fill value ($)",
                "Profit/loss booked ($)", "Why", "Cycle"], [22, 11, 10, 9, 12, 14, 15, 14, 70, 8])
    for r, f in enumerate(fills, start=2):
        wt.append([f["time"].replace("T", " ")[:19], f["tag"], "buy" if f["qty"] > 0 else "sell", f["symbol"],
                   abs(f["qty"]), f["price"], f"=E{r}*F{r}", f["realized"], f["why"], f["cycle"]])
        for col in "FGH":
            wt[f"{col}{r}"].number_format = USD
        wt[f"E{r}"].number_format = "0.000000"
    if not fills:
        wt["L1"] = "No orders yet."

    # ---------- Equity History ----------
    we = wb.create_sheet("Equity History")
    header(we, ["Date", "Equity ($)", "Cash ($)", "Day change ($)", "Day change %", "Return since start"],
           [12, 16, 16, 16, 14, 18])
    for r, row in enumerate(eq_rows, start=2):
        we.append([row["date"], float(row["equity"]), float(row["cash"]),
                   "=0" if r == 2 else f"=B{r}-B{r-1}",
                   "=0" if r == 2 else f"=IFERROR(B{r}/B{r-1}-1,0)",
                   f"=IFERROR(B{r}/Dashboard!$B$4-1,0)"])
        for col in "BCD":
            we[f"{col}{r}"].number_format = USD
        for col in "EF":
            we[f"{col}{r}"].number_format = PCT

    # ---------- Cycles ----------
    wc = wb.create_sheet("Cycles")
    header(wc, ["Cycle", "Started", "Ended", "Ended at ($)", "Return", "Why it ended"], [8, 12, 12, 14, 10, 60])
    for r, c in enumerate(led.s["cycles"], start=2):
        wc.append([c["cycle"], c["started"], c["ended"], c["end_value"], f"=IFERROR(D{r}/{led.start}-1,0)", c["reason"]])
        wc[f"D{r}"].number_format = USD
        wc[f"E{r}"].number_format = PCT
    if not led.s["cycles"]:
        wc["H1"] = f"Cycle {led.s['cycle']} still running (started {led.s['cycle_started']})."

    # ---------- Weekly Signals ----------
    ws2 = wb.create_sheet("Weekly Signals")
    week, sig = signals()
    header(ws2, ["ETF", "Friday close", "Prior week close", "40-wk avg", "Uptrend? (close > 40-wk)",
                 "12-month return", "Up over 12m?", "Dipped to 10-wk in last 3 wks?", "10-wk avg",
                 "Back above 10-wk?", "Up on the week?", "ALL PASS = buy candidate", "Held now?"],
                [8, 13, 13, 12, 14, 12, 11, 16, 12, 12, 11, 14, 10])
    for r, (a, c, prev, s, m, e, d) in enumerate(sig, start=2):
        ws2.append([a, c, prev, s, f"=B{r}>D{r}", m, f"=F{r}>0", d, e, f"=B{r}>I{r}", f"=B{r}>C{r}",
                    f"=AND(E{r},G{r},H{r},J{r},K{r},M{r}=\"no\")", "yes" if a in positions else "no"])
        for col in "BCDI":
            ws2[f"{col}{r}"].number_format = "#,##0.00"
        ws2[f"F{r}"].number_format = "0.0%"
    last = len(sig) + 1
    for col in "EGHJKL":
        rng = f"{col}2:{col}{last}"
        ws2.conditional_formatting.add(rng, FormulaRule(formula=[f"{col}2=TRUE"], fill=GOOD))
        ws2.conditional_formatting.add(rng, FormulaRule(formula=[f"{col}2=FALSE"], fill=BAD))
    ws2[f"A{last + 2}"] = f"Signals from the weekly close of {week:%Y-%m-%d}. The bot buys at most ONE per week (the one with the biggest 12-month return) and holds at most {P.slots}."
    ws2[f"A{last + 3}"] = "Sell rule for held ETFs: weekly close below the 40-wk avg."

    # ---------- Rules ----------
    wr = wb.create_sheet("Rules")
    wr.column_dimensions["A"].width = 110
    for line in [
        "Weekly trend + pullback ETF strategy",
        "",
        "Universe: SPY (US stocks), EFA (intl stocks), EEM (emerging), TLT (long bonds), IEF (mid bonds), GLD (gold), DBC (commodities), VNQ (real estate).",
        "Checked once a week on Friday's close; traded the following Monday (run weekly_paper.bat or run_alpaca_paper.py).",
        "",
        "BUY an ETF only if ALL are true:",
        "  1. Uptrend: close above its 40-week average AND up over the last 12 months.",
        "  2. Pullback: some weekly close in the previous 3 weeks was at/below the 10-week average (don't chase highs).",
        "  3. Bounce: this week closed back above the 10-week average AND higher than last week.",
        "  At most one new buy per week (strongest 12-month trend wins). Max 3 holdings, each 1/3 of the account.",
        "",
        "SELL when the weekly close drops below the 40-week average (trend broken). Otherwise keep holding.",
        "",
        "Weeks with no trades are normal. Judge it over months, on STRATEGY trades only.",
    ]:
        wr.append([line])
    wr["A1"].font = Font(name=FONT, bold=True, size=13)

    for sheet in wb.worksheets:
        fonts(sheet)
    wb.calculation.fullCalcOnLoad = True  # openpyxl stores no cached results; Excel computes on open
    wb.save(XLSX)
    write_html(led, eq_rows, positions, fills, week, sig)
    return XLSX


def write_html(led, eq_rows, positions, fills, week, sig):
    data = {
        "updated": f"{datetime.now(NY):%Y-%m-%d %H:%M}",
        "start_equity": led.start, "plan_size": PLAN_SIZE, "slots": P.slots,
        "cycle": led.s["cycle"], "cycle_started": led.s["cycle_started"], "cycles": led.s["cycles"],
        "equity": [{"date": r["date"], "equity": float(r["equity"]), "cash": float(r["cash"])} for r in eq_rows],
        "positions": [{"symbol": s, **p} for s, p in sorted(positions.items())],
        "trades": [{"time": f["time"].replace("T", " ")[:16], "type": f["tag"], "action": "buy" if f["qty"] > 0 else "sell",
                    "symbol": f["symbol"], "qty": abs(f["qty"]), "price": f["price"], "status": "filled",
                    "why": f["why"]} for f in fills],
        "signals": {"week": f"{week:%Y-%m-%d}",
                    "rows": [{"etf": a, "close": float(c), "prev": float(prev), "sma40": float(s), "mom12": float(m),
                              "ema10": float(e), "dipped": d, "held": a in positions}
                             for a, c, prev, s, m, e, d in sig]},
    }
    blob = json.dumps(data).replace("</", "<\\/")  # keep "</script>" inside strings from ending the data block
    HTML.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", blob), encoding="utf-8")


def main():
    api = Paper() if have_keys() else None
    try:
        path = build(api)
    except PermissionError:
        raise SystemExit(f"Couldn't save {XLSX.name}; close it in Excel and run again.")
    print(f"Tracker written: {path}")
    print(f"Dashboard written: {HTML}")


if __name__ == "__main__":
    main()
