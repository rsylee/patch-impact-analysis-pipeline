-- marts/mart_hero_stats_daily.sql
-- Daily hero-rate snapshot for the Streamlit dashboard, across all
-- collected regions and rank tiers (including the 'All' tier bucket --
-- useful as a dashboard default view even though the DiD panel excludes it).
--
-- avg() here is a defensive no-op: source data is already one row per
-- (pulled_date, region, rank_tier, role, hero_key); it just guards against
-- an accidental duplicate same-day pull.

{{ config(materialized='table') }}

select
    pulled_date,
    region,
    rank_tier,
    role,
    hero_key,
    avg(pick_rate) as avg_pick_rate,
    avg(winrate)   as avg_winrate,
    avg(ban_rate)  as avg_ban_rate
from {{ ref('stg_hero_rates') }}
group by 1, 2, 3, 4, 5
