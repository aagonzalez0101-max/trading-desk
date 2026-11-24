"""POLYMARKET NFL PROPS SCANNER -- forward collector + PAPER bets (the paper version of the 'aggressive bot', plan item 0a).
Why forward: PM-11b (11/23) found only 16% of Polymarket prop markets trade pregame, and on real trades vs FanDuel a +$8.91 / 49-ladder result
(t 2.63) that is too small to call. The only honest way to grow the sample is to log REAL order books (best ask + size, never a mid) next to
the sharp lines every slate.
Each pass:
  1. Pinnacle (guest API) + FanDuel (public sportsbook JSON) NFL player-prop fair probabilities (ported from ../sports betting _props.py /
     _fanduel.py so this runs on GitHub). FanDuel alt-ladder prices are one-sided: fair = implied - an assumed 4.5% hold (logged as such).
  2. Polymarket open NFL '*-player-props' markets -> real /book best bid/ask + size for Over and Under.
  3. Exact-line join (player, stat, line). Every matched row -> collected/props/<UTC date>.jsonl.gz (deduped like the speed collector).
  4. PAPER signal: sharp fair - (best ask + fee 0.05*p*(1-p)) >= 3c with >= 5 shares at that ask, pregame (>= 15 min to kickoff), one per
     market -> core.ledger PAPER/STRATEGY 'pm_props_scan@<ref>' (results/props_trades.jsonl). Settled from gamma when the market resolves.
Pinnacle and FanDuel signals are logged as separate strategies so each reference gets its own record (PM-11b's pre-declared two-reference test).
    python -m strategies.pm_props_scan once
    python -m strategies.pm_props_scan run 335      # loop every 10 min for 335 min (GitHub job)
"""
import datetime, gzip, json, os, re, sys, time, unicodedata
from concurrent.futures import ThreadPoolExecutor
import requests

from core import guard, ledger

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "collected", "props")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36", "Accept": "application/json"}
PIN = "https://guest.api.arcadia.pinnacle.com/0.1"
PIN_KEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"          # the public guest key pinnacle.com ships
FD = "https://sbapi.nj.sportsbook.fanduel.com/api"; FD_AK = "FhMFpcPWXMeyZxOx"
G = "https://gamma-api.polymarket.com"; C = "https://clob.polymarket.com"
STAT = {"passing_yards": "passing yards", "rushing_yards": "rushing yards", "receiving_yards": "receiving yards", "receptions": "receptions"}
FD_STAT = {"receptions": "receptions", "receivingyds": "receiving yards", "receivingyards": "receiving yards", "rushingyds": "rushing yards",
           "rushingyards": "rushing yards", "passingyds": "passing yards", "passingyards": "passing yards"}
EDGE, MIN_SIZE, PRE, SHARES = 0.03, 5, 900, 10
DRY = "--dry" in sys.argv          # local test: no ledger writes (the GitHub job owns the cloud ledger file)
S = requests.Session(); S.headers.update(H)


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("'", "").replace(".", "")
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def j(url, **kw):
    for k in range(3):
        try:
            r = S.get(url, timeout=30, **kw)
            if r.status_code == 200 and r.text:
                return r.json()
        except Exception:
            pass
        time.sleep(1 + 2 * k)
    return None


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


# ---------------------------------------------------------------- sharp references
def pinnacle():
    M = j(f"{PIN}/leagues/889/matchups", headers={"X-API-Key": PIN_KEY}) or []
    K = j(f"{PIN}/leagues/889/markets/straight", headers={"X-API-Key": PIN_KEY}) or []
    sp = {m["id"]: m for m in M if m.get("type") == "special" and (m.get("special") or {}).get("category") == "Player Props"}
    out = {}
    for k in K:
        m = sp.get(k.get("matchupId"))
        if not m or k.get("type") != "total":
            continue
        names = {p["id"]: p["name"] for p in m["participants"]}
        pr = {names.get(p.get("participantId")): (p.get("points"), p["price"]) for p in k["prices"]}
        if "Over" not in pr or "Under" not in pr:
            continue
        mm = re.match(r"(.+?) Total (.+)$", m["special"]["description"])
        if not mm:
            continue
        o, u = 1 / dec(pr["Over"][1]), 1 / dec(pr["Under"][1])
        out[(norm(mm.group(1)), mm.group(2).lower(), float(pr["Over"][0]))] = round(o / (o + u), 4)
    return out


def fanduel():
    d = j(f"{FD}/content-managed-page", params=dict(page="CUSTOM", customPageId="nfl", _ak=FD_AK, timezone="America/Chicago")) or {}
    ev = [e for e in ((d.get("attachments") or {}).get("events") or {}).values() if " @ " in e.get("name", "")]
    imp = lambda a: 100 / (a + 100) if a > 0 else -a / (-a + 100)

    def one(eid):
        out = {}
        for tab in ("receiving-props", "rushing-props", "passing-props"):
            x = j(f"{FD}/event-page", params=dict(_ak=FD_AK, eventId=eid, tab=tab)) or {}
            for m in (x.get("attachments") or {}).get("markets", {}).values():
                name = m.get("marketName", "")
                if " - " not in name:
                    continue
                player, mt = name.split(" - ", 1)
                alt = mt.lower().startswith("alt ")
                st = FD_STAT.get(re.sub(r"[^a-z]", "", re.sub(r"(?i)^(alt|total)\s+", "", mt).lower()))
                if not st:
                    continue
                R = m.get("runners") or []
                if alt:
                    for r in R:
                        mm = re.search(r"(\d+)\+", r.get("runnerName", ""))
                        am = (((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds"))
                        if mm and am is not None:
                            out[(norm(player), st, int(mm.group(1)) - 0.5)] = round(max(0.01, imp(am) * (1 - 0.045)), 4)
                else:
                    ov = next((r for r in R if "over" in r.get("runnerName", "").lower()), None)
                    un = next((r for r in R if "under" in r.get("runnerName", "").lower()), None)
                    if ov and un:
                        po = imp(ov["winRunnerOdds"]["americanDisplayOdds"]["americanOdds"]); pu = imp(un["winRunnerOdds"]["americanDisplayOdds"]["americanOdds"])
                        out[(norm(player), st, float(ov.get("handicap") or 0))] = round(po / (po + pu), 4)
        return out
    out = {}
    with ThreadPoolExecutor(4) as ex:
        for p in ex.map(lambda e: one(e["eventId"]), ev):
            out.update(p)
    return out


# ---------------------------------------------------------------- polymarket
def poly_markets():
    now = datetime.datetime.now(datetime.timezone.utc)
    evs, off = [], 0
    while off < 2000:                                    # 100 per page max; a date window keeps season-long markets out
        page = j(f"{G}/events", params=dict(tag_slug="nfl", closed="false", limit=100, offset=off, end_date_min=now.isoformat(timespec="seconds"),
                                            end_date_max=(now + datetime.timedelta(days=8)).isoformat(timespec="seconds"))) or []
        evs += page; off += 100
        if len(page) < 100:
            break
    out = []
    for e in evs:
        if "player-props" not in e.get("slug", ""):
            continue
        for m in e.get("markets", []):
            st = STAT.get(m.get("sportsMarketType")); q = m.get("question") or ""
            if not st or ":" not in q or m.get("line") is None or m.get("closed"):
                continue
            try:
                toks = json.loads(m["clobTokenIds"]); outs = json.loads(m["outcomes"])
            except Exception:
                continue
            if outs[:2] != ["Over", "Under"]:
                continue
            gs = m.get("gameStartTime")
            start = datetime.datetime.fromisoformat(gs.replace(" ", "T").replace("+00", "+00:00")).timestamp() if gs else None
            out.append(dict(ev=e["slug"], slug=m.get("slug"), cid=m.get("conditionId"), who=norm(q.split(":")[0]), stat=st, line=float(m["line"]),
                            start=start, over=toks[0], under=toks[1], fee=(m.get("feeSchedule") or {}).get("rate", 0.05)))
    return out


def book(tok):
    b = j(f"{C}/book", params=dict(token_id=tok)) or {}
    bids = [(float(x["price"]), float(x["size"])) for x in b.get("bids", [])]
    asks = [(float(x["price"]), float(x["size"])) for x in b.get("asks", [])]
    bb = max(bids) if bids else (None, 0); ba = min(asks) if asks else (None, 0)
    return dict(bid=bb[0], ask=ba[0], ask_size=ba[1])


# ---------------------------------------------------------------- the pass
_last = {}


def settle():
    """close paper trades whose Polymarket market has resolved."""
    with ledger.using(ledger.PROPS):
        opens = [r for r in ledger.open_trades() if r["strategy"].startswith("pm_props_scan")]
        for r in opens:
            cid = (r.get("note") or "").split("cid=")[-1].split()[0] if "cid=" in (r.get("note") or "") else None
            if not cid:
                continue
            ms = j(f"{G}/markets", params=dict(condition_ids=cid)) or []
            if not ms or not ms[0].get("closed"):
                continue
            px = [float(x) for x in json.loads(ms[0]["outcomePrices"])]
            pay = px[0] if r["side"] == "OVER" else px[1]
            fm = re.search(r"fee ([0-9.]+)", r.get("note") or "")
            net = r["qty"] * (pay - r["entry"] - (float(fm.group(1)) if fm else 0.0))
            ledger.close_trade(r["id"], exit=pay, net=net, note="settled %.2f" % pay)


def once():
    now = time.time(); ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    pm = [m for m in poly_markets() if m["start"] and m["start"] - now > PRE]
    if not pm:
        return ts, 0, 0
    refs = {"pinnacle": pinnacle(), "fanduel": fanduel()}
    hit = [m for m in pm if any((m["who"], m["stat"], m["line"]) in R for R in refs.values())]
    with ThreadPoolExecutor(8) as ex:
        books = list(ex.map(lambda m: (book(m["over"]), book(m["under"])), hit))
    os.makedirs(OUT, exist_ok=True)
    n_sig = 0
    with gzip.open(os.path.join(OUT, ts[:10] + ".jsonl.gz"), "at", encoding="utf-8") as f, ledger.using(ledger.PROPS):
        open_syms = {r["symbol"] for r in ledger.open_trades() if r["strategy"].startswith("pm_props_scan")}
        for m, (bo, bu) in zip(hit, books):
            key = (m["who"], m["stat"], m["line"])
            row = dict(ts=ts, ev=m["ev"], slug=m["slug"], who=m["who"], stat=m["stat"], line=m["line"], start=m["start"],
                       pin=refs["pinnacle"].get(key), fd=refs["fanduel"].get(key), over=bo, under=bu)
            sig = (row["pin"], row["fd"], bo["ask"], bu["ask"], bo["ask_size"], bu["ask_size"])
            if _last.get(m["slug"]) != sig:
                _last[m["slug"]] = sig
                f.write(json.dumps(row) + "\n")
            for ref in ("pinnacle", "fanduel"):
                p = row["pin" if ref == "pinnacle" else "fd"]
                if p is None:
                    continue
                for side, b, pw in (("OVER", bo, p), ("UNDER", bu, 1 - p)):
                    a = b["ask"]
                    if a is None or not (0.03 < a < 0.97) or b["ask_size"] < MIN_SIZE:
                        continue
                    fee = m["fee"] * a * (1 - a)
                    sym = f"{m['slug']}|{side}|{ref}"
                    if pw - a - fee >= EDGE and sym not in open_syms:
                        name = f"pm_props_scan@{ref}"
                        ok, why = (True, "dry") if DRY else guard.allow("PAPER", SHARES * a, strategy=name, max_open=500)
                        if not ok:
                            continue
                        if DRY:
                            print("  DRY signal", name, sym, "ask %.3f fair %.3f" % (a, pw)); n_sig += 1; continue
                        ledger.open_trade("PAPER", "STRATEGY", name, "polymarket", sym, side, SHARES, a, SHARES * a,
                                          note=f"fair {pw:.3f} ask {a:.3f} fee {fee:.4f} size {b['ask_size']:.0f} mins_to_kick "
                                               f"{(m['start'] - now) / 60:.0f} cid={m['cid']}")
                        open_syms.add(sym); n_sig += 1
        f.write(json.dumps(dict(ts=ts, src="pass", poly=len(pm), matched=len(hit), signals=n_sig,
                                pin=len(refs["pinnacle"]), fd=len(refs["fanduel"]))) + "\n")
    if n_sig:
        try:
            from core.notify import send
            send("SIGNAL", f"props scan: {n_sig} paper bet(s) where the Polymarket ask beats the sharp fair by >= 3c")
        except Exception:
            pass
    return ts, len(hit), n_sig


if __name__ == "__main__":
    if sys.argv[1:2] == ["run"]:
        end = time.time() + 60 * float(sys.argv[2] if len(sys.argv) > 2 else 335)
        while time.time() < end:
            t0 = time.time()
            try:
                settle(); print(*once(), flush=True)
            except Exception as e:
                print("pass failed:", e, flush=True)
            time.sleep(max(30, 600 - (time.time() - t0)))
    else:
        if not DRY:
            settle()
        print(*once())
