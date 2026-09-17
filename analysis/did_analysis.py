"""
analysis/did_analysis.py

Estimates the causal effect of Overwatch balance patches on hero pick_rate
(and winrate) using Difference-in-Differences (DiD) regression.

Model:
pick_rate = b0 + b1*is_post + b2*(is_treated*is_post)
+ C(rank_tier) + C(hero_key) + error

(No standalone is_treated term: it never varies within a hero, so it's
exactly collinear with C(hero_key) and would just burn a degree of freedom
that the hero fixed effects already spend better.)

b2 (is_treated:is_post) = ATT: the causal effect of the patch on pick_rate,
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
import logging

import pandas as pd
import statsmodels.formula.api as smf

from load.bigquery_loader import get_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = "ow-patch-impact"

# A patch needs at least this many distinct post-patch scrape days on record
# before it's treated as an analyzable event. A patch that landed today (0
# post-days) has literally no after-data yet -- pooling it in wouldn't be
# "comparing before and after," it'd be adding a treated hero to the
# regression with only pre-period rows, which just adds noise. As more days
# accumulate this threshold naturally lets a new patch phase in on its own.
MIN_POST_DAYS = 3


def load_panel() -> pd.DataFrame:
    client = get_client()
    query = f"SELECT * FROM `{PROJECT_ID}.ow_marts.mart_patch_event_panel`"
    df = client.query(query).to_dataframe()
    # Patch-day snapshots are pulled at 11:05am ET, before patches typically
    # go live later that day -- day 0 is pre-patch data, not post. (>0, not
    # >=0.) Also drop day 0 outright rather than counting it as pre: it's
    # genuinely ambiguous which side of the patch a given day-0 pull landed
    # on, and it's a single observation either way.
    df = df[df["days_since_patch"] != 0].copy()
    df["is_post"] = (df["days_since_patch"] > 0).astype(int)

    post_days_per_patch = (
        df[df["is_post"] == 1].groupby("patch_date")["pulled_date"].nunique()
    )
    ready = post_days_per_patch[post_days_per_patch >= MIN_POST_DAYS].index
    not_ready = post_days_per_patch[post_days_per_patch < MIN_POST_DAYS]
    all_patch_dates = df["patch_date"].unique()
    never_seen_post = set(all_patch_dates) - set(post_days_per_patch.index)
    for pd_ in sorted(not_ready.index) + sorted(never_seen_post):
        n = int(post_days_per_patch.get(pd_, 0))
        logger.info(f"Excluding patch {pd_} from analysis: only {n} post-patch day(s) "
                    f"on record (need {MIN_POST_DAYS}) -- too recent to compare before/after yet.")

    return df[df["patch_date"].isin(ready)].copy()


def find_mixed_heroes(df: pd.DataFrame) -> set:
    """(patch_date, hero_key) pairs that got BOTH a buff line and a nerf line
    in the same patch. Their net effect is ambiguous -- a hero with both
    isn't "actually a nerf" just because a nerf-tagged bullet is what joins
    to a given regression's filter; excluded from both pure-direction arms
    rather than silently assigned to whichever change_type row happens to
    match. (Confirmed concretely for the 2026-09-08 patch: brigitte, sierra,
    vendetta, winston all got a buff AND a nerf line; including them in the
    "nerf" arm masked a real ~1.3pp winrate decline visible in the other 8
    nerf-only heroes.)"""
    directional = df[df["change_type"].isin(["buff", "nerf"])]
    n_types = directional.groupby(["patch_date", "hero_key"])["change_type"].nunique()
    return set(n_types[n_types > 1].index)


def scope_for_change_type(df: pd.DataFrame, change_type: str) -> pd.DataFrame:
    """The subset of the panel that's actually valid to compare for one
    change_type (buff/nerf/rework) -- shared by run_did and event_study so
    the regression and its diagnostic plot always agree on what they're
    looking at.

    Two scoping rules prevent control rows from leaking across concurrent
    patches (confirmed concretely: every 2026-09-08 nerf-treated hero also
    shows up as a is_treated=0 control relative to the 2026-09-10 patch,
    since they're same-role and untouched by that bugfix-only patch --
    without scoping, the SAME hero/day enters one regression labeled both
    treated and control):
      - controls are drawn only from patch_date(s) that actually have a
        treated hero of this change_type, not pooled across every patch_date
        in the panel.
      - mixed buff+nerf heroes (see find_mixed_heroes) are dropped from both
        pure-direction arms.
    """
    mixed = find_mixed_heroes(df)
    hero_patch = pd.Series(list(zip(df["patch_date"], df["hero_key"])), index=df.index)
    is_mixed_row = hero_patch.isin(mixed)

    relevant_patch_dates = df.loc[
        (df["change_type"] == change_type) & ~is_mixed_row, "patch_date"
    ].unique()
    in_scope = df["patch_date"].isin(relevant_patch_dates)

    return df[
        in_scope
        & (((df["change_type"] == change_type) & ~is_mixed_row) | (df["is_treated"] == 0))
    ].copy()


def run_did(df: pd.DataFrame, change_type: str = "buff", outcome: str = "pick_rate"):
    """Run DiD for a single change_type (buff/nerf/rework) and outcome variable.
    Standard errors are clustered at the hero level. See scope_for_change_type
    for why the subset isn't just a naive change_type/is_treated filter."""
    subset = scope_for_change_type(df, change_type)

    # Standalone is_treated is dropped: it never varies within a hero, so
    # it's exactly collinear with C(hero_key) and just eats a degree of
    # freedom for nothing. That collinearity was always there, but shrinking
    # the sample to fix the leakage above pushed hero-cluster count (~40-43)
    # close enough to parameter count (~50-53) that the cluster-robust
    # sandwich covariance went singular (NaN SEs) -- dropping this one
    # redundant column restores full column rank.
    formula = f"{outcome} ~ is_post + is_treated:is_post + C(rank_tier) + C(hero_key)"
    model = smf.ols(formula=formula, data=subset).fit(
        cov_type="cluster",
        cov_kwds={"groups": subset["hero_key"]},
    )
    return model, subset


def summarize_effect(model, n_treated_heroes: int) -> dict:
    coef_name = "is_treated:is_post"
    return {
        "effect_estimate": model.params.get(coef_name),
        "std_err": model.bse.get(coef_name),
        "p_value": model.pvalues.get(coef_name),
        "ci_95": model.conf_int().loc[coef_name].tolist(),
        # cluster-robust SEs are degenerate with too few clusters -- a single
        # treated hero (e.g. a lone rework) produces artificially tiny SEs
        # and spurious near-zero p-values, not a real precise estimate.
        "unreliable_se": n_treated_heroes < 4,
        "n_treated_heroes": n_treated_heroes,
    }


if __name__ == "__main__":
    panel = load_panel()
    for outcome in ["pick_rate", "winrate", "ban_rate"]:
        print(f"\n{'='*60}")
        print(f"Outcome: {outcome}")
        for change in ["buff", "nerf", "rework"]:
            if not (panel["change_type"] == change).any():
                print(f"\n  [{change.upper()}] no {change} events in the current "
                      f"analyzable window -- nothing to estimate")
                continue
            try:
                model, subset = run_did(panel, change_type=change, outcome=outcome)
                n_treated = subset[subset["is_treated"] == 1]["hero_key"].nunique()
                result = summarize_effect(model, n_treated)
                print(f"\n  [{change.upper()}] (n_treated_heroes={n_treated})")
                print(f"  Estimate : {result['effect_estimate']:.3f} pts")
                print(f"  SE       : {result['std_err']:.3f}")
                print(f"  p-value  : {result['p_value']:.4f}")
                print(f"  95% CI   : {result['ci_95']}")
                if result["unreliable_se"]:
                    print(f"  ** UNRELIABLE: only {n_treated} treated hero(es) -- cluster-robust "
                          f"SE is degenerate with this few clusters. Don't read this p-value "
                          f"as significance. **")
            except Exception as e:  # noqa: BLE001 -- intentionally broad: one
                # outcome/change_type combo failing (e.g. empty subset,
                # singular design matrix) shouldn't kill the whole report loop
                print(f"  [{change.upper()}] skipped: {e}")