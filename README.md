# Overwatch Patch Impact Analytics Pipeline

End-to-end ETL + causal inference pipeline that tracks how Overwatch balance
patches (buffs/nerfs/reworks) causally affect hero pick rate, win rate, and
ban rate, broken out by region and rank tier. Ban rate is included as a
leading indicator alongside the two lagging ones: players tend to ban on
reputation ("this buff made them scary") before pick/win rate fully catch
up, so a patch's effect can show up there first, or show up there even
when the win-rate effect is still too noisy to be significant.

## Why this project

Traditional "patch impact" write-ups on Reddit/YouTube are purely
descriptive (before/after pick rate). This project treats each patch as a
natural experiment and applies difference-in-differences + event-study
methodology to separate the *causal* effect of a balance change from
natural meta drift.

## Data sources & scope

Blizzard's official [Hero Statistics page](https://overwatch.blizzard.com/en-us/rates/)
publishes population-level pick rate, win rate, and ban rate per hero,
filterable by region, rank tier, and game mode. Per that page's own FAQ,
"All stats are pulled from the start of the most recent patch" — so these
numbers are already patch-scoped, not lifetime/career-cumulative stats.

The page is server-rendered: the full per-hero payload for a given
(region, tier) request is embedded directly in the initial HTML response
as JSON in a custom `<blz-data-table allrows="...">` element, so it's
scraped with plain `requests` + `BeautifulSoup` — no browser automation
needed (verified against the live page).

Every day, `extract/hero_rates_scraper.py` cycles through 3 regions ×
9 rank tiers (27 requests) to build a full daily snapshot. The causal
analysis itself (`mart_patch_event_panel`) is scoped to `region = 'Americas'`
and excludes Blizzard's own cross-tier `'All'` bucket — see the comments in
`transform/models/marts/mart_patch_event_panel.sql` for why. Asia/Europe
and the `'All'` tier are still collected and available in the dashboard.

An earlier version of this project scraped Blizzard's Top 500 leaderboard
for battletags and queried the OverFast API per player — that approach was
dropped once this page turned out to publish population-level rates
directly, which is a better source (no per-player sampling/selection bias,
no lifetime-cumulative stats diluting patch-window signal, no rate-limited
per-player HTTP calls).

## Architecture

Extract (hero rates scrape + patch notes scrape) → Load
(BigQuery) → Transform (dbt, with automated data-quality tests) → Analyze
(DiD, panel regression, event studies) → Orchestrate (Airflow, daily) →
Visualize (Streamlit dashboard)

```
extract/
├── hero_rates_scraper.py   # Blizzard's official Hero Statistics page
└── patch_notes_scraper.py  # patch notes page → buff/nerf/rework events

load/bigquery_loader.py     # raw CSVs → BigQuery ow_raw

transform/                  # dbt project
├── models/staging/stg_hero_rates.sql, stg_patch_notes.sql
└── models/marts/mart_hero_stats_daily.sql, mart_patch_event_panel.sql

analysis/
├── did_analysis.py         # Difference-in-Differences regression
└── event_study.py          # parallel-trends event-study plots

orchestration/dags/patch_impact_dag.py   # Airflow DAG, daily
dashboard/app.py            # Streamlit dashboard
```

## Tech stack

Python · BigQuery · dbt · Airflow · Streamlit · GitHub Actions ·
statsmodels (DiD, panel fixed-effects) · Docker

## Setup

1. **BigQuery**: create a GCP project, a service account with BigQuery
   Data Editor + Job User roles, and the `ow_raw` / `ow_marts` datasets.
2. Copy `.env.example` to `.env` and fill in your project/dataset names.
3. `pip install -r requirements.txt`
4. `python -m extract.hero_rates_scraper && python -m extract.patch_notes_scraper`
5. `python -m load.bigquery_loader`
6. `cd transform && dbt run --profiles-dir . && dbt test --profiles-dir .`
7. `python -m analysis.did_analysis`
8. `streamlit run dashboard/app.py`

`docker-compose up` runs Airflow (daily automated extract → load → dbt →
analysis) plus the Streamlit dashboard as containers.

## Limitations & mitigations

**Sample size isn't disclosed.** Blizzard doesn't publish the number of
games behind each pick/win/ban rate. Rarely-picked heroes, mirror
matchups, and freshly-released patches show up as `"--"` in the raw
payload — the scraper converts these to `null` rather than guessing a
value, and `mart_patch_event_panel`/`did_analysis.py` don't backfill them.
There's no way to attach a confidence interval to Blizzard's own numbers
the way there would be with raw per-player counts.

**Win rate is cumulative-since-patch-start, not a daily rate.** Because
the source resets at the start of each patch, `days_since_patch = 1`
reflects roughly one day of games while `days_since_patch = 20` reflects
about twenty — so early post-patch observations carry more noise than
later ones. Worth keeping in mind when reading `did_analysis.py` output
or the event-study plots, not something the code currently corrects for.

**No historical backfill.** The page reflects the *current* patch only —
there's no way to retroactively pull rates for a patch that has already
ended. Causal analysis is only possible for patches observed after this
pipeline started running daily.

**Parallel-trends assumption isn't guaranteed.** `event_study.py` checks
this visually (treated/control pick rate, win rate, and ban rate should track
together before day 0), but confounders that land in the same patch as a
hero's balance change — map pool changes, other heroes' changes shifting
the counter-pick landscape — aren't controlled for in the regression.

**Region scope.** The DiD panel is fixed to Americas to avoid mixing
metas that may differ structurally by region; Asia/Europe data is
collected and available for the dashboard but not the causal analysis.
Extending the model to include region as a fixed effect (rather than
filtering it out) is a reasonable next step if regional comparisons
become interesting.

## Résumé bullets

- Built an automated ETL pipeline (Airflow, dbt, BigQuery) scraping
  Blizzard's official Hero Statistics page daily across 3 regions and 9
  rank tiers to track Overwatch hero pick-rate and win-rate shifts across
  balance patches; applied difference-in-differences and event-study
  analysis to estimate the causal impact of buffs/nerfs.
- Designed and deployed a CI/CD-tested (GitHub Actions), containerized
  (Docker) data pipeline with dbt-based data quality tests and a public
  Streamlit dashboard visualizing hero meta trends by region and rank tier.
