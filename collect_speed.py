"""PM-7 collector: Pinnacle vs Kalshi vs Polymarket game moneylines, snapshotted every ~2 minutes (free, no keys beyond Pinnacle's
public guest key). Rows -> data/speed/<UTC date>.jsonl, one line per source per game per pass. Analysis comes later (>= 100 signals).
    python collect_speed.py once
    python collect_speed.py loop [seconds]       # default 120
"""
import datetime, json, os, sys, time
import requests

H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
PIN = "https://guest.api.arcadia.pinnacle.com/0.1"
PIN_KEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"          # the public guest key pinnacle.com ships (same as the betting desk)
KAL = "https://api.elections.kalshi.com/trade-api/v2"
GAM = "https://gamma-api.polymarket.com"
LEAGUES = {"nfl": (889, "KXNFLGAME", "nfl"), "nba": (487, "KXNBAGAME", "nba"), "nhl": (1456, "KXNHLGAME", "nhl"),
           "cfb": (880, "KXNCAAFGAME", "cfb")}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "speed")
S = requests.Session(); S.headers.update(H)


def j(url, **kw):
    try:
        r = S.get(url, timeout=25, **kw)
        return r.json() if r.status_code == 200 and r.text else None
    except Exception:
        return None


def dec(a):
    a = float(a)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def pinnacle(lid):
    mu = j(f"{PIN}/leagues/{lid}/matchups?brandId=0", headers={"X-API-Key": PIN_KEY}) or []
    mk = j(f"{PIN}/leagues/{lid}/markets/straight", headers={"X-API-Key": PIN_KEY}) or []
    px = {m["matchupId"]: {p.get("designation"): p.get("price") for p in m.get("prices", [])}
          for m in mk if m.get("key") == "s;0;m" and not m.get("isAlternate")}
    out = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for m in mu:
        if m.get("parentId") or m.get("type") != "matchup" or m["id"] not in px:
            continue
        p = px[m["id"]]
        if p.get("home") is None or p.get("away") is None:
            continue
        st = datetime.datetime.fromisoformat(m["startTime"].replace("Z", "+00:00"))
        if not (now < st < now + datetime.timedelta(hours=36)):
            continue                                   # pregame only, next 36h
        side = {q["alignment"]: q["name"] for q in m.get("participants", [])}
        ih, ia = 1 / dec(p["home"]), 1 / dec(p["away"])
        out.append(dict(id=m["id"], t=m["startTime"], home=side.get("home"), away=side.get("away"),
                        ph=round(ih / (ih + ia), 4), pa=round(ia / (ih + ia), 4), ml=[p["home"], p["away"]]))
    return out


def soon(t, hours=36):
    """pregame and starting within `hours` (exchange timestamps come as ISO or 'YYYY-MM-DD HH:MM:SS+00')."""
    if not t:
        return False
    try:
        st = datetime.datetime.fromisoformat(t.replace(" ", "T").replace("Z", "+00:00").replace("+00", "+00:00").replace("+00:00:00", "+00:00"))
    except ValueError:
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    return now < st < now + datetime.timedelta(hours=hours)


def kalshi(series):
    r = j(f"{KAL}/markets", params=dict(series_ticker=series, status="open", limit=1000)) or {}
    return [dict(tk=m["ticker"], ev=m["event_ticker"], team=m.get("yes_sub_title"), t=m.get("occurrence_datetime"),
                 ask=m.get("yes_ask_dollars"), bid=m.get("yes_bid_dollars")) for m in r.get("markets", []) if soon(m.get("occurrence_datetime"))]


def poly(tag):
    now = datetime.datetime.now(datetime.timezone.utc)
    r = j(f"{GAM}/events", params=dict(tag_slug=tag, closed="false", limit=500, end_date_min=now.isoformat(timespec="seconds"),
                                       end_date_max=(now + datetime.timedelta(hours=60)).isoformat(timespec="seconds"))) or []
    out = []
    for e in r:
        for m in e.get("markets", []):
            if m.get("sportsMarketType") == "moneyline" and m.get("slug") == e.get("slug") and soon(m.get("gameStartTime")):
                out.append(dict(slug=m["slug"], t=m.get("gameStartTime"), outcomes=m.get("outcomes"),
                                bid=m.get("bestBid"), ask=m.get("bestAsk"), last=m.get("lastTradePrice"), prices=m.get("outcomePrices")))
    return out


KEYS = {"pin": ("id", ("ph", "pa")), "kal": ("tk", ("ask", "bid")), "poly": ("slug", ("bid", "ask", "last"))}
_last = {}


def once(out_dir=OUT, dedupe=True):
    """one pass -> gzipped jsonl per UTC day. dedupe: only rows whose prices changed since the previous pass, plus one 'pass' heartbeat
    row (so a gap in the data = collector down, not 'nothing moved')."""
    import gzip
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    n = seen = 0
    run = os.getenv("GITHUB_RUN_ID", "local")            # one file per run: two runs never touch the same file (11/24 merge-conflict data loss)
    with gzip.open(os.path.join(out_dir, f"{ts[:10]}_{run}.jsonl.gz"), "at", encoding="utf-8") as f:
        for lg, (lid, ser, tag) in LEAGUES.items():
            for src, rows in (("pin", pinnacle(lid)), ("kal", kalshi(ser)), ("poly", poly(tag))):
                kf, vf = KEYS[src]
                for r in rows:
                    seen += 1
                    key = (src, r.get(kf)); val = tuple(r.get(v) for v in vf)
                    if dedupe and _last.get(key) == val:
                        continue
                    _last[key] = val
                    f.write(json.dumps(dict(ts=ts, src=src, lg=lg, **r)) + "\n"); n += 1
        f.write(json.dumps(dict(ts=ts, src="pass", seen=seen, written=n)) + "\n")
    return ts, n, seen


def loop(every=120, minutes=None, out_dir=OUT):
    end = time.time() + 60 * minutes if minutes else None
    while end is None or time.time() < end:
        t0 = time.time()
        try:
            print(*once(out_dir), flush=True)
        except Exception as e:
            print("pass failed:", e, flush=True)
        time.sleep(max(5, every - (time.time() - t0)))


if __name__ == "__main__":
    # cloud (GitHub Action): python collect_speed.py run 340  -> ~5.7h of passes into collected/speed/, committed at the end
    if sys.argv[1:2] == ["run"]:
        loop(120, float(sys.argv[2]) if len(sys.argv) > 2 else 340,
             os.path.join(os.path.dirname(os.path.abspath(__file__)), "collected", "speed"))
    elif sys.argv[1:2] == ["loop"]:
        loop(int(sys.argv[2]) if len(sys.argv) > 2 else 120)
    else:
        print(*once())
