"""
tests/test_hero_rates_scraper.py

Unit tests for extract/hero_rates_scraper.py. All HTTP calls are mocked --
no network access required.

Sample HTML mirrors the real <blz-data-table allrows="..."> structure
verified against the live page (2026-08).
"""
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from extract.hero_rates_scraper import fetch_hero_rates, parse_rows, collect_all, REGIONS, TIERS


SAMPLE_HTML = (
    '<div class="herostats-datatable">'
    '<blz-data-table class="herostats-data-table" allrows=\'[{"id":"ana",'
    '"cells":{"name":"Ana","winrate":49,"pickrate":26.1,"banrate":12.2},'
    '"hero":{"name":"Ana","subrole":"tactician","role":"SUPPORT"}},'
    '{"id":"anran","cells":{"name":"Anran","winrate":"--","pickrate":"--","banrate":"--"},'
    '"hero":{"name":"Anran","subrole":"vanguard","role":"TANK"}}]\'>'
    "</blz-data-table></div>"
)


@patch("extract.hero_rates_scraper.requests.get")
def test_fetch_hero_rates_parses_allrows_attribute(mock_get):
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_HTML
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    rows = fetch_hero_rates("Americas", "All")
    assert len(rows) == 2
    assert rows[0]["id"] == "ana"
    assert rows[0]["cells"]["pickrate"] == 26.1


@patch("extract.hero_rates_scraper.requests.get")
def test_fetch_hero_rates_missing_table_returns_empty(mock_get):
    mock_resp = MagicMock()
    mock_resp.text = "<html><body>no data table here</body></html>"
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    rows = fetch_hero_rates("Americas", "All")
    assert rows == []  # pipeline must not crash if the page structure changes


def test_parse_rows_flattens_fields():
    rows = [{
        "id": "ana",
        "cells": {"name": "Ana", "winrate": 49, "pickrate": 26.1, "banrate": 12.2},
        "hero": {"name": "Ana", "subrole": "tactician", "role": "SUPPORT"},
    }]
    parsed = parse_rows("Americas", "All", rows, "2026-08-20T00:00:00+00:00")
    assert len(parsed) == 1
    r = parsed[0]
    assert r["hero_key"] == "ana"
    assert r["region"] == "Americas"
    assert r["tier"] == "All"
    assert r["role"] == "SUPPORT"
    assert r["winrate"] == 49
    assert r["pickrate"] == 26.1
    assert r["banrate"] == 12.2


def test_parse_rows_converts_dash_placeholders_to_none():
    """'--' means Blizzard doesn't have enough data yet (see page FAQ)."""
    rows = [{
        "id": "anran",
        "cells": {"name": "Anran", "winrate": "--", "pickrate": "--", "banrate": "--"},
        "hero": {"name": "Anran", "subrole": "vanguard", "role": "TANK"},
    }]
    parsed = parse_rows("Americas", "All", rows, "2026-08-20T00:00:00+00:00")
    r = parsed[0]
    assert r["winrate"] is None
    assert r["pickrate"] is None
    assert r["banrate"] is None


@patch("extract.hero_rates_scraper.time.sleep")
@patch("extract.hero_rates_scraper.fetch_hero_rates")
def test_collect_all_covers_every_region_tier_combination(mock_fetch, mock_sleep):
    mock_fetch.return_value = [{
        "id": "ana",
        "cells": {"name": "Ana", "winrate": 49, "pickrate": 26.1, "banrate": 12.2},
        "hero": {"name": "Ana", "subrole": "tactician", "role": "SUPPORT"},
    }]
    df = collect_all()
    assert isinstance(df, pd.DataFrame)
    assert mock_fetch.call_count == len(REGIONS) * len(TIERS)
    assert set(df["region"].unique()) == set(REGIONS)
    assert set(df["tier"].unique()) == set(TIERS)
