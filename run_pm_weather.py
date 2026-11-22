"""PM-6: Kalshi daily-high temperature markets vs a free day-old forecast (pre-declared in results/sweep_log.csv).
Forecast archive: Open-Meteo previous-runs API (free, no key). Kalshi: settled KXHIGH markets + 1-min candles (public).
    python run_pm_weather.py fetch [days]
    python run_pm_weather.py
"""
import collections, datetime, json, math, os, random, sys
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
import numpy as np

from core.backtest import report, tstat
from run_pm_sharp_study import get, ts

K = "https://api.elections.kalshi.com/trade-api/v2"
OUT = "data/pm_weather"
CITY = {  # series: (lat, lon, tz) -- the settlement stations Kalshi names
    "KXHIGHNY": (40.7789, -73.9692, "America/New_York"), "KXHIGHCHI": (41.7868, -87.7522, "America/Chicago"),
    "KXHIGHMIA": (25.7959, -80.2870, "America/New_York"), "KXHIGHAUS": (30.1945, -97.6699, "America/Chicago"),
    "KXHIGHLAX": (33.9425, -118.4081, "America/Los_Angeles"), "KXHIGHDEN": (39.8561, -104.6737, "America/Denver"),
    "KXHIGHPHIL": (39.8721, -75.2411, "America/New_York")}
EDGE, SLIP, WARM = 0.05, 0.01, 30


def day_of(event_ticker):
    return datetime.datetime.strptime(event_ticker.split("-")[1], "%y%b%d").date()


def fetch(days=90):
    os.makedirs(OUT, exist_ok=True)
    end = datetime.date.today(); start = end - datetime.timedelta(days=days + 2)
    for ser, (lat, lon, tz) in CITY.items():
        ff = os.path.join(OUT, ser + "_fc.json")
        if not os.path.exists(ff):
            j = get("https://previous-runs-api.open-meteo.com/v1/forecast", latitude=lat, longitude=lon,
                    hourly="temperature_2m_previous_day1", temperature_unit="fahrenheit", timezone=tz,
                    start_date=str(start), end_date=str(end))
            h = j["hourly"]; fc = collections.defaultdict(list)
            for t, v in zip(h["time"], h["temperature_2m_previous_day1"]):
                if v is not None:
                    fc[t[:10]].append(v)
            json.dump({d: max(v) for d, v in fc.items() if len(v) >= 20}, open(ff, "w"))
        mf = os.path.join(OUT, ser + "_mk.json")
        if not os.path.exists(mf):
            ms, cur = [], None
            while True:
                p = dict(series_ticker=ser, status="settled", limit=1000, min_close_ts=int(datetime.datetime.combine(start, datetime.time()).timestamp()))
                if cur:
                    p["cursor"] = cur
                j = get(K + "/markets", **p)
                ms += [{k: m.get(k) for k in ("ticker", "event_ticker", "strike_type", "floor_strike", "cap_strike", "result")} for m in j.get("markets", [])]
                cur = j.get("cursor")
                if not cur or not j.get("markets"):
                    break
            json.dump(ms, open(mf, "w"))
        ms = json.load(open(mf))
        print(ser, "markets", len(ms), "days", len({m["event_ticker"] for m in ms}), flush=True)

        def one(m):
            f = os.path.join(OUT, m["ticker"] + ".json")
            if os.path.exists(f):
                return
            d = day_of(m["event_ticker"])
            D = datetime.datetime.combine(d, datetime.time(8, 0), ZoneInfo(tz)).timestamp()
            j = get(f"{K}/series/{ser}/markets/{m['ticker']}/candlesticks", start_ts=int(D - 3600), end_ts=int(D), period_interval=1)
            c = [(x["end_period_ts"], (x.get("yes_ask") or {}).get("close_dollars"), (x.get("yes_bid") or {}).get("close_dollars"))
                 for x in (j or {}).get("candlesticks", [])]
            json.dump(c, open(f, "w"))
        with ThreadPoolExecutor(6) as ex:
            list(ex.map(one, ms))


def bracket(m):
    """-> (lo, hi) inclusive integer range the market pays on."""
    t = m["strike_type"]; f, c = m.get("floor_strike"), m.get("cap_strike")
    if t == "greater":
        return math.floor(f) + 1, 999
    if t == "less":
        return -999, math.ceil(c) - 1
    return math.ceil(f), math.floor(c)


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def fee(c):
    return 0.07 * c * (1 - c)


def run(edge=EDGE, placebo=False, seed=3):
    rnd = random.Random(seed); out = []
    for ser, (lat, lon, tz) in CITY.items():
        fc = json.load(open(os.path.join(OUT, ser + "_fc.json")))
        ms = json.load(open(os.path.join(OUT, ser + "_mk.json")))
        ev = collections.defaultdict(list)
        for m in ms:
            ev[m["event_ticker"]].append(m)
        actual = {}
        for e, mm in ev.items():
            w = [bracket(m) for m in mm if m["result"] == "yes"]
            if len(w) == 1:
                lo, hi = w[0]
                actual[str(day_of(e))] = (lo + hi) / 2 if lo > -999 and hi < 999 else (lo if hi == 999 else hi)
        days = sorted(actual)
        for e in sorted(ev, key=day_of):
            d = str(day_of(e))
            prior = [x for x in days if x < d and x in fc][-WARM:]
            if len(prior) < WARM or d not in fc:
                continue
            errs = [actual[x] - fc[x] for x in prior]
            bias, sd = float(np.mean(errs)), max(1.0, float(np.std(errs, ddof=1)))
            F = fc[d] if not placebo else fc[rnd.choice([x for x in fc if x != d])]
            D = datetime.datetime.combine(day_of(e), datetime.time(8, 0), ZoneInfo(tz)).timestamp()
            for m in ev[e]:
                f = os.path.join(OUT, m["ticker"] + ".json")
                if not os.path.exists(f):
                    continue
                q = [x for x in json.load(open(f)) if D - 3600 <= x[0] <= D and x[1] is not None and x[2] is not None]
                if not q:
                    continue
                ask, bid = float(q[-1][1]), float(q[-1][2])
                lo, hi = bracket(m); mu = F + bias
                p = ncdf((hi + 0.5 - mu) / sd) - ncdf((lo - 0.5 - mu) / sd)
                if 0.02 <= ask <= 0.98 and p - ask - fee(ask) - SLIP >= edge:
                    out.append(dict(city=ser, day=d, side="YES", p=p, c=ask, net=(1 - ask if m["result"] == "yes" else -ask) - fee(ask) - SLIP))
                na = 1 - bid
                if 0.02 <= na <= 0.98 and (1 - p) - na - fee(na) - SLIP >= edge:
                    out.append(dict(city=ser, day=d, side="NO", p=1 - p, c=na, net=(1 - na if m["result"] == "no" else -na) - fee(na) - SLIP))
    return out


def per_cd(tr):
    h = collections.defaultdict(float)
    for t in tr:
        h[(t["day"], t["city"])] += t["net"]
    k = sorted(h)
    return [h[x] for x in k], k


def main():
    tr = run()
    print("PM-6 trades %d (YES %d / NO %d)" % (len(tr), sum(t["side"] == "YES" for t in tr), sum(t["side"] == "NO" for t in tr)))
    if not tr:
        return
    print("  per contract: net $%+.2f avg %+.4f, won %.1f%% vs model-expected %.1f%%, avg price %.3f" % (
        sum(t["net"] for t in tr), np.mean([t["net"] for t in tr]), 100 * np.mean([t["net"] > 0 for t in tr]),
        100 * np.mean([t["p"] for t in tr]), np.mean([t["c"] for t in tr])))
    for c in CITY:
        v = [t["net"] for t in tr if t["city"] == c]
        if v:
            print("  %-10s n=%3d net $%+.2f" % (c, len(v), sum(v)))
    for s in ("YES", "NO"):
        v = [t["net"] for t in tr if t["side"] == s]
        print("  %s n=%d net $%+.2f avg %+.4f" % (s, len(v), sum(v), np.mean(v) if v else 0))
    nets, keys = per_cd(tr)
    report("PM-6 kalshi_daily_high_vs_forecast, per CITY-DAY totals ($ per 1 contract each)", nets, keys)
    for e in (0.04, 0.06):
        n2, _ = per_cd(run(e)); print("  edge >= %dc: city-days %d net $%+.2f t %+.2f" % (100 * e, len(n2), sum(n2), tstat(n2)))
    n3, _ = per_cd(run(placebo=True)); print("  placebo (forecast from a random other day): city-days %d net $%+.2f t %+.2f" % (len(n3), sum(n3), tstat(n3)))
    d = collections.defaultdict(float)
    for t in tr:
        d[t["day"]] += t["net"]
    print("  days %d; drop best 2 days: $%+.2f -> $%+.2f" % (len(d), sum(d.values()), sum(d.values()) - sum(sorted(d.values())[-2:])))


if __name__ == "__main__":
    fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 90) if "fetch" in sys.argv else main()
