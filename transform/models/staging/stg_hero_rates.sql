-- staging/stg_hero_rates.sql
--
-- Raw table is already population-level (Blizzard's own aggregated
-- pick/win/ban rate per hero, per region, per rank tier, per day) -- no
-- player-level rows to aggregate here. This model just types and renames.
--
-- rank_tier includes Blizzard's own 'All' bucket (cross-tier aggregate),
-- which mart_patch_event_panel deliberately excludes -- it's a marginal
-- aggregate over the other 8 tiers, not an independent stratum.

with source as (
    select * from {{ source('ow_raw', 'hero_rates') }}
),

typed as (
    select
        cast(pulled_at as timestamp)       as pulled_at,
        date(cast(pulled_at as timestamp)) as pulled_date,
        region,                                          -- 'Americas' / 'Asia' / 'Europe'
        tier                                as rank_tier, -- 'All' / 'Bronze' .. 'Grandmaster'
        case tier
            when 'All'         then 0
            when 'Bronze'      then 1
            when 'Silver'      then 2
            when 'Gold'        then 3
            when 'Platinum'    then 4
            when 'Emerald'     then 5
            when 'Diamond'     then 6
            when 'Master'      then 7
            when 'Grandmaster' then 8
        end                                 as rank_tier_ordinal,
        lower(hero_key)                     as hero_key,
        hero_name,
        lower(role)                         as role,
        subrole,
        safe_cast(winrate as float64)       as winrate,
        safe_cast(pickrate as float64)      as pick_rate,
        safe_cast(banrate as float64)       as ban_rate
    from source
    where hero_key is not null
)

select * from typed
