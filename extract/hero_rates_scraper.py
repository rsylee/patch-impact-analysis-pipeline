"""
extract/hero_rates_scraper.py

This script scrapes Blizzard's official Hero Statistics page
(overwatch.blizzard.com/en-us/rates/) for pick/win/ban rates per hero,
broken out by region and rank tier (only competitive mode; not quick-play).

Uses requests to pull the page HTML, then BeautifulSoup to locate the
<blz-data-table> element and parse its "allrows" attribute as JSON.
"""
import time
import logging
import json
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RATES_URL = "https://overwatch.blizzard.com/en-us/rates/"
REGIONS = ["Americas", "Asia", "Europe"]
TIERS = ["All", "Bronze", "Silver", "Gold", "Platinum", "Emerald", "Diamond", "Master", "Grandmaster"]
ROLE = "All"        # cosmetic only -- doesn't filter server-side, see module docstring
MAP_FILTER = "all-maps"
GAME_MODE = "2"     # rq=2 = "Competitive - Role Queue" (rq=0 = "Quick Play - Role Queue")
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
    """Cycle through every (region, tier) combination -- 3 regions x 9 tiers
    = 27 requests -- and return one combined DataFrame."""
    pulled_at = datetime.now(timezone.utc).isoformat()
    all_rows = []
    for region in REGIONS:
        for tier in TIERS:
            rows = fetch_hero_rates(region, tier)
            all_rows.extend(parse_rows(region, tier, rows, pulled_at))
            time.sleep(1)  # polite delay between requests
    return pd.DataFrame(all_rows)


if __name__ == "__main__":
    import os
    os.makedirs("data/raw/hero_rates", exist_ok=True)
    df = collect_all()
    df.to_csv("data/raw/hero_rates/hero_rates_latest.csv", index=False)
    logger.info(f"Saved {len(df)} hero-rate rows")
