"""
tests/test_did_analysis.py

Unit tests for analysis/did_analysis.py using synthetic panel data.
No BigQuery connection needed — load_panel() is mocked.
"""
from unittest.mock import patch

import pandas as pd
import numpy as np
import pytest

from analysis.did_analysis import run_did, summarize_effect


def make_synthetic_panel(n_heroes: int = 10, n_days: int = 20, seed: int = 42) -> pd.DataFrame:
    """Generate a small synthetic DiD panel with a known treatment effect."""
    rng = np.random.default_rng(seed)
    rows = []
    treated_heroes = [f"hero_{i}" for i in range(n_heroes // 2)]
    control_heroes = [f"hero_{i}" for i in range(n_heroes // 2, n_heroes)]

    for day in range(-n_days // 2, n_days // 2):
        for hero in treated_heroes:
            is_post = int(day >= 0)
            pick_rate = 5.0 + 2.0 * is_post + rng.normal(0, 0.5)  # true effect = +2
            rows.append({
                "days_since_patch": day,
                "is_treated": 1,
                "hero_key": hero,
                "rank_tier": "Gold",
                "change_type": "buff",
                "pick_rate": pick_rate,
                "winrate": 50.0 + rng.normal(0, 1),
                "ban_rate": 3.0 + rng.normal(0, 0.5),
            })
        for hero in control_heroes:
            pick_rate = 5.0 + rng.normal(0, 0.5)
            rows.append({
                "days_since_patch": day,
                "is_treated": 0,
                "hero_key": hero,
                "rank_tier": "Gold",
                "change_type": None,
                "pick_rate": pick_rate,
                "winrate": 50.0 + rng.normal(0, 1),
                "ban_rate": 3.0 + rng.normal(0, 0.5),
            })

    df = pd.DataFrame(rows)
    df["is_post"] = (df["days_since_patch"] >= 0).astype(int)
    return df


def test_run_did_returns_model():
    panel = make_synthetic_panel()
    model = run_did(panel, change_type="buff", outcome="pick_rate")
    assert model is not None


def test_summarize_effect_keys():
    panel = make_synthetic_panel()
    model = run_did(panel, change_type="buff", outcome="pick_rate")
    result = summarize_effect(model)
    assert "effect_estimate" in result
    assert "std_err" in result
    assert "p_value" in result
    assert "ci_95" in result
    assert len(result["ci_95"]) == 2


def test_did_detects_positive_effect():
    """With a synthetic +2pp treatment effect, the DiD estimate should be positive."""
    panel = make_synthetic_panel(seed=0)
    model = run_did(panel, change_type="buff", outcome="pick_rate")
    result = summarize_effect(model)
    assert result["effect_estimate"] > 0, "DiD should detect the positive treatment effect"


def test_run_did_winrate_outcome():
    panel = make_synthetic_panel()
    model = run_did(panel, change_type="buff", outcome="winrate")
    result = summarize_effect(model)
    assert result["effect_estimate"] is not None


def test_run_did_ban_rate_outcome():
    panel = make_synthetic_panel()
    model = run_did(panel, change_type="buff", outcome="ban_rate")
    result = summarize_effect(model)
    assert result["effect_estimate"] is not None
