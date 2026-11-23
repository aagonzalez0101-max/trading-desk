"""KICKER -- the scheduler that actually fires. GitHub's cron never triggered in this repo (11/22-23: speed.yml and phase2.yml
schedules never ran), so the always-on speed-collector job runs this alongside its loop and starts the trading workflows itself
via `gh workflow run` (a workflow_dispatch started with the job's token DOES create a run).
Targets (UTC, weekdays): phase2 'fomc' at 17:15, phase2 'daily' at 21:30. Each is started once per UTC day, within a 45-min window,
and only if no phase2 run with that job already exists today (scheduled runs count too). Duplicates are harmless anyway:
run_phase2.py does nothing the second time once the month's decision is made, and the FOMC buy checks the ledger first.
    python kicker.py 335        # check every minute for 335 minutes
"""
import datetime, json, subprocess, sys, time

TARGETS = [("fomc", 17, 15), ("daily", 21, 30)]
WINDOW = 45


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def ran_today(job, now):
    code, out, _ = gh("run", "list", "--workflow", "phase2.yml", "--limit", "40", "--json", "createdAt,displayTitle,event")
    if code:
        return True                                   # can't tell -> don't risk a storm of dispatches
    day = now.date().isoformat()
    sched = {"fomc": "15 17,18", "daily": "30 21"}[job]
    for r in json.loads(out or "[]"):
        if r["createdAt"][:10] == day and (job in r["displayTitle"] or sched in r["displayTitle"]):
            return True
    return False


def tick():
    now = datetime.datetime.now(datetime.timezone.utc)
    if now.weekday() >= 5:
        return
    for job, h, m in TARGETS:
        t0 = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if t0 <= now <= t0 + datetime.timedelta(minutes=WINDOW) and not ran_today(job, now):
            code, out, err = gh("workflow", "run", "phase2.yml", "--ref", "main", "-f", f"job={job}")
            print(now.isoformat(timespec="seconds"), "kicked phase2", job, "->", code, out or err, flush=True)


if __name__ == "__main__":
    end = time.time() + 60 * float(sys.argv[1] if len(sys.argv) > 1 else 335)
    while time.time() < end:
        try:
            tick()
        except Exception as e:
            print("kicker error:", e, flush=True)
        time.sleep(60)
