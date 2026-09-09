-- marts/mart_patch_event_panel.sql
--
-- Core analysis table: for each patch event, attaches pre- and post-patch
-- hero stats in a panel format ready for Difference-in-Differences regression.
--
-- treatment group: heroes that received a patch change
-- control group:   other heroes in the same role that were NOT changed in that patch
-- window: 21 days before and after each patch date
--
-- Scope: filtered to region = 'Americas' and excludes the 'All' rank_tier
-- bucket.
--   - Region is fixed to avoid blurring the causal estimate across metas
--     that may differ by region (Asia/Europe are still collected in
--     stg_hero_rates for the dashboard, just not mixed into this panel).
--   - 'All' is Blizzard's own cross-tier aggregate, not an independent
--     stratum -- including it alongside the 8 real tiers as a 9th
--     C(rank_tier) level would double-count information already present
--     in those 8 rows.

{{ config(materialized='table') }}

with patches as (
    select * from {{ ref('stg_patch_notes') }}
),

stats as (
    select * from {{ ref('stg_hero_rates') }}
    where region = 'Americas'
      and rank_tier != 'All'
),

-- Treated heroes: received a change in this patch
treated as (
    select
        p.patch_date,
        p.hero_key,
        p.change_type,
        s.pulled_date,
        s.rank_tier,
        s.rank_tier_ordinal,
        s.role,
        s.pick_rate,
        s.winrate,
        s.ban_rate,
        date_diff(s.pulled_date, p.patch_date, day) as days_since_patch,
        1                                            as is_treated
    from patches p
    join stats s
        on p.hero_key = s.hero_key
        and s.pulled_date between date_sub(p.patch_date, interval 21 day)
                               and date_add(p.patch_date, interval 21 day)
),

-- Roles that received at least one change in a given patch, used to find
-- same-role, non-patched heroes as controls for that patch
patched_roles as (
    select distinct
        p.patch_date,
        s.role
    from patches p
    join stats s on s.hero_key = p.hero_key
),

-- Control heroes: same role, NOT changed in this patch, same time window
control as (
    select
        pr.patch_date,
        s.hero_key,
        cast(null as string)                          as change_type,
        s.pulled_date,
        s.rank_tier,
        s.rank_tier_ordinal,
        s.role,
        s.pick_rate,
        s.winrate,
        s.ban_rate,
        date_diff(s.pulled_date, pr.patch_date, day)   as days_since_patch,
        0                                               as is_treated
    from patched_roles pr
    join stats s
        on s.role = pr.role
        and s.pulled_date between date_sub(pr.patch_date, interval 21 day)
                               and date_add(pr.patch_date, interval 21 day)
    left join patches p
        on p.patch_date = pr.patch_date
        and p.hero_key = s.hero_key
    where p.hero_key is null
)

select * from treated
union all
select * from control
