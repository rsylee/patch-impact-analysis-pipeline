-- staging/stg_patch_notes.sql
--
-- Casts and cleans the raw patch events table.
-- magnitude_unit distinguishes two kinds of changes:
--   'absolute' -> value went from A to B (e.g. damage 60 -> 65, magnitude = +5)
--   'percent'  -> changed by N% (e.g. ultimate cost +7%, magnitude = +7)
-- Rows with unclassified change_type are excluded here; they still exist in raw.

with source as (
    select * from {{ source('ow_raw', 'patch_events') }}
)

select
    date(patch_date)                    as patch_date,
    lower(hero_key)                     as hero_key,
    change_type,
    stat_name,
    safe_cast(magnitude as float64)     as magnitude,
    magnitude_unit,                     -- 'absolute' | 'percent'
    change_text,
    review_needed
from source
where change_type != 'unclassified'    -- rows that need manual review are excluded from marts
