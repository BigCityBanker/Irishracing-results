"""Supabase (Postgres) storage. New tables only: nothing here touches the old ho_* tables."""
import json

import psycopg2
import psycopg2.extras

SCHEMA_SQL = """
create schema if not exists racing;

create table if not exists racing.ir_race (
    race_url            text primary key,
    race_date           date not null,
    course              text,
    course_slug         text,
    country             text,
    is_point_to_point   boolean,
    sched_time          time,
    off_time            text,
    race_name           text,
    race_class          int,
    age_text            text,
    distance_text       text,
    distance_yards      int,
    going               text,
    currency            text,
    total_prize_text    text,
    prizes              jsonb,
    runners             int,
    winning_time_text   text,
    winning_time_secs   double precision,
    bets_text           text,
    non_runners         text,
    scraped_at          timestamptz default now()
);

create table if not exists racing.ir_runner (
    race_url            text references racing.ir_race(race_url) on delete cascade,
    row_index           int,
    position            text,
    dist_text           text,
    saddle_cloth        int,
    draw                int,
    horse_name          text,
    horse_country       text,
    horse_id            int,
    age                 int,
    colour              text,
    sex                 text,
    weight              text,
    weight_lbs          int,
    official_rating     int,
    headgear            text,
    headgear_count      int,
    headgear_desc       text,
    stewards_mention    boolean,
    owner               text,
    sire                text,
    sire_country        text,
    dam                 text,
    dam_country         text,
    damsire             text,
    damsire_country     text,
    breeder             text,
    morning_prices      text,
    ring_prices         text,
    sp                  text,
    sp_decimal          double precision,
    sp_fav              text,
    trainer             text,
    trainer_id          int,
    jockey              text,
    jockey_id           int,
    jockey_claim        int,
    tote                text,
    comment             text,
    silk                text,
    primary key (race_url, row_index)
);
create index if not exists ir_runner_horse_idx on racing.ir_runner (horse_id);

create table if not exists racing.ir_day (
    race_date    date primary key,
    races_found  int,
    races_saved  int,
    done         boolean default false,
    error        text,
    updated_at   timestamptz default now()
);
"""

RACE_COLS = ["race_url", "race_date", "course", "course_slug", "country", "is_point_to_point",
             "sched_time", "off_time", "race_name", "race_class", "age_text", "distance_text",
             "distance_yards", "going", "currency", "total_prize_text", "prizes", "runners",
             "winning_time_text", "winning_time_secs", "bets_text", "non_runners"]

RUNNER_COLS = ["race_url", "row_index", "position", "dist_text", "saddle_cloth", "draw",
               "horse_name", "horse_country", "horse_id", "age", "colour", "sex", "weight",
               "weight_lbs", "official_rating", "headgear", "headgear_count", "headgear_desc",
               "stewards_mention", "owner", "sire", "sire_country", "dam", "dam_country",
               "damsire", "damsire_country", "breeder", "morning_prices", "ring_prices", "sp",
               "sp_decimal", "sp_fav", "trainer", "trainer_id", "jockey", "jockey_id",
               "jockey_claim", "tote", "comment", "silk"]


def connect(url):
    extra = {"sslmode": "require"} if "supabase" in url and "sslmode" not in url else {}
    conn = psycopg2.connect(url, connect_timeout=30, **extra)
    conn.autocommit = False
    return conn


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def done_days(conn):
    with conn.cursor() as cur:
        cur.execute("select race_date from racing.ir_day where done")
        return {r[0] for r in cur.fetchall()}


def save_race(conn, race, runners):
    """Replace one race and its runners in a single transaction."""
    race = dict(race)
    race["prizes"] = json.dumps(race.get("prizes") or [])
    with conn.cursor() as cur:
        cur.execute("delete from racing.ir_race where race_url = %s", (race["race_url"],))
        cur.execute(
            f"insert into racing.ir_race ({','.join(RACE_COLS)}) values ({','.join(['%s'] * len(RACE_COLS))})",
            [race.get(c) for c in RACE_COLS])
        if runners:
            rows = [[dict(r, race_url=race["race_url"]).get(c) for c in RUNNER_COLS] for r in runners]
            psycopg2.extras.execute_values(
                cur, f"insert into racing.ir_runner ({','.join(RUNNER_COLS)}) values %s", rows)
    conn.commit()


def mark_day(conn, d, found, saved, done, error=None):
    with conn.cursor() as cur:
        cur.execute("""
            insert into racing.ir_day (race_date, races_found, races_saved, done, error, updated_at)
            values (%s, %s, %s, %s, %s, now())
            on conflict (race_date) do update set races_found = excluded.races_found,
                races_saved = excluded.races_saved, done = excluded.done,
                error = excluded.error, updated_at = now()""",
                    (d, found, saved, done, error))
    conn.commit()
