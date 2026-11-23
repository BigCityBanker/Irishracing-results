# IrishRacing results archive

Fetches UK and Irish race results from irishracing.com, one page about every 5 seconds,
and stores them in a Supabase Postgres database (schema `racing`, tables `ir_race`,
`ir_runner`, `ir_day`). It never touches any other tables.

Runs on GitHub Actions every 6 hours (`.github/workflows/scrape.yml`). Each run carries on
from the oldest unfinished day, so the first runs backfill from 17 Oct 2021 and later runs
just add the latest days.

Setup: add a repository secret `DATABASE_URL` holding the Supabase **Session pooler**
connection string (GitHub's computers can't use the direct connection).

Data source: irishracing.com. Its terms allow free use of the content, with attribution
when republished. This repository contains code only, no race data.
