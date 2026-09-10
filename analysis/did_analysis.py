"""
analysis/did_analysis.py

Estimates the causal effect of Overwatch balance patches on hero pick_rate
(and winrate) using Difference-in-Differences (DiD) regression.

Model: 
pick_rate = b0 + b1*is_treated + b2*is_post + b3*(is_treated*is_post)
+ C(rank_tier) + C(hero_key) + error

b3 (is_treated:is_post) = ATT: the causal effect of the patch on pick_rate,
controlling for hero and rank-tier fixed effects.

Outcomes:
- pick_rate, winrate: co-primary. winrate is patch-scoped (Blizzard's Hero
  Stats page resets each patch, not lifetime-cumulative), so it moves
  within a patch window. Caveat: each day's value is a cumulative average
  since patch start (days_since_patch=1 ~ 1 day of games, =20 ~ 20 days),
  so early post-patch observations are noisier than later ones.
- ban_rate: secondary. Hypothesized leading indicator -- players ban on
  reputation ("this got buffed") faster than pick/win rate fully reflect
  the change, so patch effects may surface here first.
"""
import pandas as pd
import statsmodels.formula.api as smf

from load.bigquery_loader import get_client

PROJECT_ID = "ow-patch-impact"


def load_panel() -> pd.DataFrame:
    client = get_client()
    query = f"SELECT * FROM `{PROJECT_ID}.ow_marts.mart_patch_event_panel`"
    df = client.query(query).to_dataframe()
    df["is_post"] = (df["days_since_patch"] >= 0).astype(int)
    return df


def run_did(df: pd.DataFrame, change_type: str = "buff", outcome: str = "pick_rate"):
    """Run DiD for a single change_type (buff/nerf/rework) and outcome variable.
    Standard errors are clustered at the hero level to be conservative."""
    subset = df[
        (df["change_type"] == change_type) | (df["is_treated"] == 0)
    ].copy()

    formula = f"{outcome} ~ is_treated * is_post + C(rank_tier) + C(hero_key)"
    model = smf.ols(formula=formula, data=subset).fit(
        cov_type="cluster",
        cov_kwds={"groups": subset["hero_key"]},
    )
    return model


def summarize_effect(model) -> dict:
    coef_name = "is_treated:is_post"
    return {
        "effect_estimate": model.params.get(coef_name),
        "std_err": model.bse.get(coef_name),
        "p_value": model.pvalues.get(coef_name),
        "ci_95": model.conf_int().loc[coef_name].tolist(),
    }


if __name__ == "__main__":
    panel = load_panel()
    for outcome in ["pick_rate", "winrate", "ban_rate"]:
        print(f"\n{'='*60}")
        print(f"Outcome: {outcome}")
        for change in ["buff", "nerf", "rework"]:
            try:
                model = run_did(panel, change_type=change, outcome=outcome)
                result = summarize_effect(model)
                print(f"\n  [{change.upper()}]")
                print(f"  Estimate : {result['effect_estimate']:.3f} pts")
                print(f"  SE       : {result['std_err']:.3f}")
                print(f"  p-value  : {result['p_value']:.4f}")
                print(f"  95% CI   : {result['ci_95']}")
            except Exception as e:
                print(f"  [{change.upper()}] skipped: {e}")