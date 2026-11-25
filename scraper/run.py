"""Fetch irishracing.com results day by day and store them in Supabase.

Usage:
  python -m scraper.run --test                 # fetch one known page, print what was parsed, no database
  python -m scraper.run                        # normal run: oldest unfinished days first, until time budget
Environment:
  DATABASE_URL   Supabase Postgres connection string (GitHub secret)
"""
import argparse
import os
import random
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from scraper import parse

BASE = "https://www.irishracing.com"
USER_AGENT = "personal-racing-research/0.1 (slow results archive; one request every ~5s)"
START_DATE = date(2021, 10, 17)   # first day missing from the old Racing Post data


class Blocked(Exception):
    pass


class Fetcher:
    def __init__(self, min_delay=4.0, max_delay=6.0):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html"})
        self.min_delay, self.max_delay = min_delay, max_delay
        self.last = 0.0
        self.count = 0

    def get(self, path):
        """Return page HTML, or None for 404. Raises Blocked on 403/406."""
        for attempt in range(4):
            wait = self.last + random.uniform(self.min_delay, self.max_delay) - time.time()
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                r = self.s.get(BASE + path, timeout=60)
            except requests.RequestException as e:
                print(f"  network error on {path}: {e}; waiting 60s", flush=True)
                time.sleep(60)
                continue
            self.count += 1
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return None
            if r.status_code in (403, 406):
                raise Blocked(f"HTTP {r.status_code} on {path}")
            if r.status_code == 429 or r.status_code >= 500:
                print(f"  HTTP {r.status_code} on {path}; backing off 10 minutes", flush=True)
                time.sleep(600)
                continue
            raise RuntimeError(f"unexpected HTTP {r.status_code} on {path}")
        raise RuntimeError(f"gave up on {path} after retries")


def scrape_day(f, d):
    """Return (race paths on the day page, [(path, race, runners) for each race fetched])."""
    html = f.get(f"/raceresults/{parse.day_slug(d)}")
    if html is None:
        return [], []
    all_paths = parse.parse_day(html, d)
    paths = [p for p in all_paths if parse.is_uk_ire(p.split("/")[3])]
    skipped = sorted({p.split("/")[3] for p in all_paths if p not in paths})
    if skipped:
        print(f"  {d}: skipping non-UK/IRE meetings: {', '.join(skipped)}", flush=True)
    out = []
    for p in paths:
        page = f.get(p)
        if page is None:
            print(f"  404 for {p}, skipped", flush=True)
            continue
        race, runners = parse.parse_race(page, p)
        race["race_date"] = d
        out.append((p, race, runners))
    return paths, out


def run_test():
    f = Fetcher()
    d = date(2021, 10, 16)
    html = f.get(f"/raceresults/{parse.day_slug(d)}")
    paths = parse.parse_day(html or "", d)
    print(f"Day page {parse.day_slug(d)}: found {len(paths)} races")
    p = "/raceresults/Sat-16th-Oct-2021/Ascot/1325"
    race, runners = parse.parse_race(f.get(p), p)
    print(f"Race: {race['course']} {race['sched_time']} {race['race_name']} | "
          f"{race['distance_text']} | class {race['race_class']} | {race['going']} | "
          f"{race['runners']} ran | time {race['winning_time_secs']}s")
    for r in runners[:3]:
        print(f"  {r['position']:>4} {r['horse_name']} ({r['horse_country']}) age {r.get('age')} "
              f"draw {r['draw']} OR {r['official_rating']} SP {r['sp']} "
              f"J {r['jockey']} T {r['trainer']} | {r.get('sire')} - {r.get('dam')} ({r.get('damsire')})")
    ok = len(paths) > 20 and len(runners) == 10 and runners[0]["horse_name"] == "Trueshan"
    print("TEST PASSED" if ok else "TEST FAILED")
    return 0 if ok else 1


def run(max_minutes, start, end, redo_recent):
    from scraper import db
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set (add it as a GitHub secret)")
        return 1
    conn = db.connect(url)
    db.ensure_schema(conn)
    finished = db.done_days(conn)
    recent = {end - timedelta(days=i) for i in range(redo_recent)}
    todo = []
    d = start
    while d <= end:
        if d not in finished or d in recent:
            todo.append(d)
        d += timedelta(days=1)
    print(f"{len(todo)} days to do between {start} and {end} "
          f"({len(finished)} already finished)", flush=True)

    f = Fetcher()
    deadline = time.time() + max_minutes * 60
    empty_streak = 0
    days_done = races_done = 0
    for d in todo:
        if time.time() > deadline:
            print("Time budget used up; the next run carries on from here.")
            out = os.environ.get("GITHUB_OUTPUT")
            if out:
                with open(out, "a") as fh:
                    fh.write("more=true\n")
            break
        try:
            paths, items = scrape_day(f, d)
            for p, race, runners in items:
                db.save_race(conn, race, runners)
            races_done += len(items)
            complete = len(items) == len(paths)
            db.mark_day(conn, d, len(paths), len(items), complete,
                        None if complete else "some race pages missing")
            days_done += 1
            print(f"{d}: {len(items)}/{len(paths)} races saved "
                  f"({f.count} pages fetched so far)", flush=True)
            empty_streak = empty_streak + 1 if not paths else 0
            if empty_streak >= 4:
                print("4 days in a row with no races found: the site layout may have changed. Stopping.")
                return 3
        except parse_errors() as e:
            conn.rollback()
            db.mark_day(conn, d, None, None, False, f"{type(e).__name__}: {e}"[:500])
            print(f"{d}: FAILED ({type(e).__name__}: {e}); will retry next run", flush=True)
        except Blocked as e:
            print(f"BLOCKED: {e}. Stopping so we don't push our luck.")
            return 2
    print(f"Run finished: {days_done} days, {races_done} races, {f.count} pages fetched.")
    return 0


def parse_errors():
    return (ValueError, KeyError, IndexError, AttributeError, TypeError, RuntimeError)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--max-minutes", type=float, default=330)
    ap.add_argument("--start", type=date.fromisoformat, default=START_DATE)
    ap.add_argument("--end", type=date.fromisoformat, default=None,
                    help="last day to fetch (default: yesterday, UK time)")
    ap.add_argument("--redo-recent", type=int, default=2,
                    help="also re-fetch the last N days even if done, to pick up late corrections")
    a = ap.parse_args()
    if a.test:
        sys.exit(run_test())
    end = a.end or (datetime.now(ZoneInfo("Europe/London")).date() - timedelta(days=1))
    sys.exit(run(a.max_minutes, a.start, end, a.redo_recent))


if __name__ == "__main__":
    main()
