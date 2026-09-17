"""
extract/patch_notes_scraper.py

This script scrapes the Overwatch official patch notes page to build a treatment-event table
with columns: (patch_date, hero_key, ability, change_type, magnitude).

Verified page structure (live page, 2026-08):
  h3: "Overwatch Retail Patch Notes – August 19, 2026"  (patch date)
  h4: "Hero Updates"                                     (section marker)
  h5: "D.Mon"                                            (hero name)
  ul > li: "Damage increased from 60 to 65."             (change bullets)

change_type classification and magnitude extraction use regex and may not
catch all edge cases, so a review_needed flag marks ambiguous rows.
"""
import os
import re
import logging
import unicodedata
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PATCH_NOTES_URL = "https://overwatch.blizzard.com/en-us/news/patch-notes/live/"

# stats where an increase is a buff (damage, healing, health, etc.)
# vs. stats where an increase is a nerf (cooldown, cost, drain, etc.)
BUFF_WHEN_INCREASED = [
    "damage", "healing", "health", "speed", "range",
    "duration", "shield", "armor", "lifesteal", "regen",
]
BUFF_WHEN_DECREASED = [
    "cooldown", "cost", "recovery", "cast time", "drain", "penalty",
]
# "new" alone is too broad -- it false-positived on "A new first-person
# bootup animation has been added" (2026-09-08, D.Mon), a cosmetic note with
# no expected effect on pick/win/ban rate, which got counted as a real
# treatment event and produced a single-hero "rework" arm with meaningless
# cluster-robust SEs. Requiring "new kit"/"new ability"/"new passive" etc.
# still catches an actual rework announcement without matching cosmetic prose.
REWORK_KEYWORDS = [
    "reworked", "redesigned",
    "new kit", "new ability", "new passive", "new ultimate", "new hero",
]

# as of 2026-09, Blizzard nests hero names under a role subheading (h4) within
# "Hero Updates" -- these aren't section boundaries, just grouping, so they
# must not reset in_hero_updates the way a real section change (e.g. "Stadium
# Updates", "Bug Fixes") does.
ROLE_SUBHEADERS = {"tank", "damage", "support"}

HERO_RATES_CSV = "data/raw/hero_rates/hero_rates_latest.csv"


def load_hero_names(csv_path: str = HERO_RATES_CSV) -> list[tuple[str, str]]:
    """(hero_name, hero_key) pairs used to spot heroes named in Bug Fixes
    prose (which has no per-hero h5 structure to key off of). Longest names
    first so e.g. "D.Va" doesn't get shadowed by a shorter overlapping name."""
    if not os.path.exists(csv_path):
        logger.warning(f"{csv_path} not found -- Bug Fixes section won't be hero-tagged")
        return []
    df = pd.read_csv(csv_path)
    pairs = df[["hero_name", "hero_key"]].drop_duplicates().dropna()
    return sorted(pairs.itertuples(index=False, name=None), key=lambda p: -len(p[0]))


def slugify_hero_name(name: str) -> str:
    """match the hero_key slug used by hero_rates_scraper.py, 
    e.g. "D.Mon" -> "dmon", "Torbjörn" -> "torbjorn", "Jetpack Cat" -> "jetpack-cat"."""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    return (
        ascii_name.lower()
        .replace(".", "").replace(":", "").replace(" ", "-")
    )

# matches "Stat increased/reduced/decreased from A to B"
# uses \d+(?:\.\d+)? to avoid capturing trailing punctuation like "22.5."
PATTERN_FROM_TO = re.compile(
    r"([a-zA-Z .]+?)\s+(increased|reduced|decreased)\s+(?:from\s+)?(\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# matches "Stat increased/reduced/decreased by N%"
PATTERN_BY_PCT = re.compile(
    r"([a-zA-Z .]+?)\s+(increased|reduced|decreased)\s+by\s+(\d+(?:\.\d+)?)%",
    re.IGNORECASE,
)


def classify_direction(stat_name: str, direction: str) -> str:
    """determine buff/nerf from stat name + direction word."""
    stat_lower = stat_name.lower()
    is_increase = direction.lower() == "increased"
    if any(k in stat_lower for k in BUFF_WHEN_INCREASED):
        return "buff" if is_increase else "nerf"
    if any(k in stat_lower for k in BUFF_WHEN_DECREASED):
        return "nerf" if is_increase else "buff"
    return "unclassified"  # ambiguous stat name — review_needed will be set True


def parse_change_line(text: str) -> dict | None:
    """extract (stat_name, change_type, magnitude, magnitude_unit) from one bullet line.
    returns None for lines that don't match any numeric-change pattern (e.g. bug fixes)."""
    if any(k in text.lower() for k in REWORK_KEYWORDS):
        return {
            "stat_name": None,
            "change_type": "rework",
            "magnitude": None,
            "magnitude_unit": None,
        }

    m = PATTERN_FROM_TO.search(text)
    if m:
        stat_name, direction, before, after = m.groups()
        before, after = float(before), float(after)
        return {
            "stat_name": stat_name.strip(),
            "change_type": classify_direction(stat_name, direction),
            "magnitude": round(after - before, 4),
            "magnitude_unit": "absolute",
        }

    m = PATTERN_BY_PCT.search(text)
    if m:
        stat_name, direction, pct = m.groups()
        pct = float(pct)
        return {
            "stat_name": stat_name.strip(),
            "change_type": classify_direction(stat_name, direction),
            "magnitude": pct if direction.lower() == "increased" else -pct,
            "magnitude_unit": "percent",
        }

    return None  # no numeric pattern matched (bug fix, QoL note, etc.) — skip


def scrape_patch_notes(hero_names: list[tuple[str, str]] | None = None) -> pd.DataFrame:
    """Scrape the live patch notes page and return a DataFrame of change events.

    Heading hierarchy used by the live page (verified 2026-08):
      h3 = patch date   e.g. "Overwatch Retail Patch Notes – August 19, 2026"
      h4 = section      e.g. "Hero Updates", "Bug Fixes"
      h5 = hero name    e.g. "D.Mon", "Tracer"
      ul > li = change bullet

    Bug Fixes bullets aren't a balance change (no treatment effect expected
    on pick/win/ban rate), but a hero named there still needs to come out of
    the DiD control group for that patch window -- a bug fix is still a
    behavioral change to that hero, just not one this pipeline can size.
    Those rows get change_type="bugfix", magnitude=None, so
    mart_patch_event_panel marks the hero is_treated=1 (excluding it from
    controls) while did_analysis.py's change_type filter naturally excludes
    it from the buff/nerf/rework treatment arms too.
    """
    if hero_names is None:
        hero_names = load_hero_names()

    resp = requests.get(PATCH_NOTES_URL, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    rows = []
    current_date = None
    in_hero_updates = False
    in_bug_fixes = False
    current_hero = None

    for tag in soup.find_all(["h3", "h4", "h5", "ul"]):
        if tag.name == "h3":
            # date heading format: "Overwatch Retail Patch Notes – August 19, 2026"
            # the separator is an en-dash (–), not a regular hyphen
            raw = tag.get_text(strip=True)
            try:
                date_part = raw.split("–")[-1].strip()  # en-dash split
                current_date = datetime.strptime(date_part, "%B %d, %Y").date()
            except ValueError:
                current_date = None
            in_hero_updates = False
            in_bug_fixes = False
            current_hero = None

        elif tag.name == "h4":
            heading_text = tag.get_text(strip=True).lower()
            if heading_text in ROLE_SUBHEADERS:
                # role grouping within the current section, not a section boundary
                continue
            in_hero_updates = heading_text == "hero updates"
            in_bug_fixes = heading_text == "bug fixes"
            current_hero = None

        elif tag.name == "h5" and in_hero_updates:
            current_hero = slugify_hero_name(tag.get_text(strip=True))

        elif tag.name == "ul" and in_hero_updates and current_hero and current_date:
            for li in tag.find_all("li", recursive=False):
                change_text = li.get_text(strip=True)
                # some bullets are tagged for an experimental mode (e.g. "(6v6)")
                # rather than the standard competitive 5v5 queue hero_rates_scraper
                # measures -- skip those, they'd be a false treatment event.
                if re.search(r"\(6v6\)\s*$", change_text):
                    continue
                parsed = parse_change_line(change_text)
                if parsed is None:
                    continue
                rows.append({
                    "patch_date": current_date,
                    "hero_key": current_hero,
                    "change_text": change_text,
                    **parsed,
                    "review_needed": parsed["change_type"] == "unclassified",
                })

        elif tag.name == "ul" and in_bug_fixes and current_date:
            for li in tag.find_all("li", recursive=False):
                change_text = li.get_text(strip=True)
                # bug-fix prose has no per-hero h5 structure -- spot hero
                # names by substring match instead, longest name first
                for hero_name, hero_key in hero_names:
                    if hero_name in change_text:
                        rows.append({
                            "patch_date": current_date,
                            "hero_key": hero_key,
                            "change_text": change_text,
                            "stat_name": None,
                            "change_type": "bugfix",
                            "magnitude": None,
                            "magnitude_unit": None,
                            "review_needed": False,
                        })
                        break  # tag the first (longest) matching hero only

    df = pd.DataFrame(rows)
    if len(df):
        logger.info(
            f"Scraped {len(df)} patch change entries, "
            f"{df['review_needed'].sum()} need manual review"
        )
    else:
        logger.warning("No patch change entries parsed — verify page heading structure")
    return df


if __name__ == "__main__":
    import os
    os.makedirs("data/raw/patch_notes", exist_ok=True)
    df = scrape_patch_notes()
    df.to_csv("data/raw/patch_notes/patch_events.csv", index=False)