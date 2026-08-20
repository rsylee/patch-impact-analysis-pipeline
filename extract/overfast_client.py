"""
A script to collect win rate, pick rate, and KDA per hero from the OverFast API
by rank tier and role, then save the output as a raw CSV file.

run: python -m extract.overfast_client
"""

import os
import time
import logging
from datetime import datetime, timezone

import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("OVERFAST_BASE_URL", "https://overfast-api.tekrop.fr")
RANK_TIERS = ["bronze", "silver", "gold", "platinum", "diamond", "master", "grandmaster", "champion"]
ROLES = ["tank", "damage", "support"]
REGION = "americas"  # set region for americas only for now

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


"""fetch hero stats for a single (rank, role, region) combination."""
def fetch_hero_stats(rank: str, role: str, region: str = REGION, retries: int = 3) -> list[dict]:
    url = f"{BASE_URL}/heroes/stats/summary" # API server url
    params = {"rank_filter": rank, "role_filter": role, "region_filter": region} # query parameter as dictionary

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"[{region}/{rank}/{role}] attempt {attempt} failed: {e}")
            time.sleep(2 ** attempt)  # exponential backoff
    raise RuntimeError(f"Failed to fetch stats for region={region}, rank={rank}, role={role} after {retries} retries")

"""iterates through all (rank, role) combinations with a fixed region of 'americas', 
fetches the data, and concatenates them into a single DataFrame with a 'pulled_at' timestamp."""
def collect_all() -> pd.DataFrame:
    pulled_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for rank in RANK_TIERS:
        for role in ROLES:
            logger.info(f"Fetching region={REGION}, rank={rank}, role={role} ...")
            data = fetch_hero_stats(rank, role, region=REGION)
            for hero in data:
                rows.append({
                    "pulled_at": pulled_at,
                    "region": REGION,
                    "rank_tier": rank,
                    "role": role,
                    "hero_key": hero.get("hero"),
                    "pick_rate": hero.get("pick_rate"),
                    "win_rate": hero.get("win_rate"),
                    "kda": hero.get("kda"),
                })
    return pd.DataFrame(rows)


def save_raw(df: pd.DataFrame, out_dir: str = "data/raw") -> str:
    os.makedirs(out_dir, exist_ok=True)
    fname = f"{out_dir}/hero_stats_{datetime.now(timezone.utc):%Y%m%d}.csv"
    df.to_csv(fname, index=False)
    logger.info(f"Saved {len(df)} rows to {fname}")
    return fname


if __name__ == "__main__":
    df = collect_all()
    save_raw(df)