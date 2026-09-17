"""
extract/hero_rates_scraper.py

This script scrapes Blizzard's official Hero Statistics page
(overwatch.blizzard.com/en-us/rates/) for pick/win/ban rates per hero,
broken out by region and rank tier (only competitive mode; not quick-play).

Uses requests to pull the page HTML, then BeautifulSoup to locate the
<blz-data-table> element and parse its "allrows" attribute as JSON.
"""
import json
import logging
import time
from datetime import datetime, timezone

import pandas as pd
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RATES_URL = "https://overwatch.blizzard.com/en-us/rates/"
REGIONS = ["Americas", "Asia", "Europe"]
TIERS = ["All", "Bronze", "Silver", "Gold", "Platinum", "Emerald", "Diamond", "Master", "Grandmaster"]
ROLE = "All"        # cosmetic only -- doesn't filter server-side, see module docstring
MAP_FILTER = "all-maps"
# rq mapping is NOT stable -- Blizzard has silently reassigned these IDs at
# least twice (2026-08-22, and again as of 2026-09-08 when this file was
# rewritten and the previous fix was lost). Verified live 2026-09-17:
# rq=1 -> real ban data (Ana banrate ~11.5, matches historical). rq=0 and
# rq=2 -> banrate=0 for every hero (a banless mode). If banrate goes
# flat-zero again, re-verify all three rq values by hand before assuming "1"
# is still right -- see the flat-zero guard in collect_all() below.
GAME_MODE = "1"
PLATFORM = "PC"


def fetch_hero_rates(region: str, tier: str, retries: int = 3) -> list[dict]:
    """Fetch the hero rates table for one (region, tier) combination."""
    params = {
        "input": PLATFORM,
        "map": MAP_FILTER,
        "region": region,
        "role": ROLE,
        "rq": GAME_MODE,
        "tier": tier,
    }
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(RATES_URL, params=params, timeout=20)
            resp.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            logger.warning(f"[{region}/{tier}] attempt {attempt} failed: {e}")
            time.sleep(2 ** attempt)
    else:
        raise RuntimeError(f"Failed to fetch hero rates for region={region}, tier={tier}")

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("blz-data-table", class_="herostats-data-table")
    if table is None or not table.get("allrows"):
        logger.warning(f"[{region}/{tier}] data table not found -- page structure may have changed")
        return []

    rows = json.loads(table["allrows"])
    logger.info(f"[{region}/{tier}] found {len(rows)} heroes")
    return rows


def parse_rows(region: str, tier: str, rows: list[dict], pulled_at: str) -> list[dict]:
    """Flatten one (region, tier) response into row dicts.
    '--' placeholder values (insufficient data -- see page FAQ) become None."""
    def clean(value):
        return None if value == "--" else value

    parsed = []
    for row in rows:
        cells = row.get("cells", {})
        hero = row.get("hero", {})
        parsed.append({
            "pulled_at": pulled_at,
            "region": region,
            "tier": tier,
            "hero_key": row.get("id"),
            "hero_name": cells.get("name"),
            "role": hero.get("role"),
            "subrole": hero.get("subrole"),
            "winrate": clean(cells.get("winrate")),
            "pickrate": clean(cells.get("pickrate")),
            "banrate": clean(cells.get("banrate")),
        })
    return parsed


def collect_all() -> pd.DataFrame:
    """Cycle through every (region, tier) combination (3 regions x 9 tiers
    = 27 requests) and return one combined DataFrame."""
    pulled_at = datetime.now(timezone.utc).isoformat()
    all_rows = []
    for region in REGIONS:
        for tier in TIERS:
            rows = fetch_hero_rates(region, tier)
            all_rows.extend(parse_rows(region, tier, rows, pulled_at))
            time.sleep(1)  # polite delay between requests
    return pd.DataFrame(all_rows)


def check_banrate_sanity(df: pd.DataFrame, zero_frac_threshold: float = 0.95) -> None:
    """Guard against the recurring rq-mode bug: if banrate comes back
    all/nearly-all zero, GAME_MODE is pointing at a banless mode again
    (Blizzard reassigned the rq IDs), not a real data pattern. Raise rather
    than silently save/load corrupted data -- see the 2026-08-22 and
    2026-09-08 incidents in project memory."""
    valid = df["banrate"].dropna()
    if len(valid) == 0:
        return
    zero_frac = (valid == 0).mean()
    if zero_frac >= zero_frac_threshold:
        raise RuntimeError(
            f"banrate is {zero_frac:.0%} zero across {len(valid)} rows -- this matches "
            f"the known rq-mode bug pattern (GAME_MODE={GAME_MODE!r} may be pointing at a "
            f"banless mode again). Refusing to save/load this snapshot. Re-verify rq=0/1/2 "
            f"live by hand before re-running."
        )


if __name__ == "__main__":
    import os
    os.makedirs("data/raw/hero_rates", exist_ok=True)
    df = collect_all()
    check_banrate_sanity(df)  # raises (non-zero exit) if the rq-mode bug has recurred
    df.to_csv("data/raw/hero_rates/hero_rates_latest.csv", index=False)
    logger.info(f"Saved {len(df)} hero-rate rows")
