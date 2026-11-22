"""Phone + Discord alerts, same channel as the sports-betting desk (notify.json: ntfy_topic and/or discord_webhook).
Every message is tagged [TRADE] so it never gets confused with a betting card.
    from core.notify import send; send("FILL", "BTC 5m UP 49c x5")
    python -m core.notify test
"""
import os, sys, json, datetime
import requests

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "notify.json")
FEED = os.path.join(ROOT, "daily_log", "feed.txt")
ICON = {"SIGNAL": "📡", "FILL": "✅", "EXIT": "🏁", "HALT": "⛔", "DAILY": "🧾", "ERROR": "⚠️", "TEST": "🔔"}


def send(kind, text, priority="default"):
    ts = datetime.datetime.now(CT).strftime("%m-%d %I:%M %p")
    line = "%s %s [TRADE] %s: %s" % (ts, ICON.get(kind, "•"), kind, text)
    os.makedirs(os.path.dirname(FEED), exist_ok=True)
    with open(FEED, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        cfg = json.load(open(CFG, encoding="utf-8"))
    except Exception:
        cfg = {}
    if cfg.get("ntfy_topic"):
        try:
            requests.post("https://ntfy.sh/" + cfg["ntfy_topic"], data=line.encode("utf-8"),
                          headers={"Priority": "high" if priority == "high" else "default", "Title": "Trading desk"}, timeout=10)
        except Exception:
            pass
    if cfg.get("discord_webhook"):
        try:
            requests.post(cfg["discord_webhook"], json={"content": line[:1900]}, timeout=10)
        except Exception:
            pass
    print(line)


if __name__ == "__main__" and sys.argv[1:2] == ["test"]:
    send("TEST", "trading desk alerts are wired")
