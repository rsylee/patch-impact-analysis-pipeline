"""
analysis/did_robustness.py

Robustness check for a single patch's nerf (or buff) effect.

1. Re-draws the event study for ONE patch date only. event_study.py pools
   every analyzable patch, so days with missing snapshots can mix different
   patches together and create jumps that aren't real.
2. Runs the DiD twice for that patch: the original spec, and one that adds a
   treated-specific linear trend (is_treated:days_since_patch), so a decline
   that was already under way before the patch isn't counted as the effect.

Usage:
    python3 -m analysis.did_robustness 2026-09-08 nerf
"""
import os
import sys

import matplotlib.pyplot as plt
import statsmodels.formula.api as smf

from analysis.did_analysis import load_panel, scope_for_change_type

BASE = "pick_rate ~ is_post + is_treated:is_post + C(rank_tier) + C(hero_key)"
WITH_TREND = BASE + " + is_treated:days_since_patch"


def fit(formula, data):
    return smf.ols(formula, data=data).fit(
        cov_type="cluster", cov_kwds={"groups": data["hero_key"]}
    )


def main(patch_date: str, change_type: str) -> None:
    panel = load_panel()
    panel = panel[panel["patch_date"].astype(str) == patch_date]
    data = scope_for_change_type(panel, change_type).dropna(subset=["pick_rate"])
    if data.empty:
        print(f"No rows for patch {patch_date} / {change_type}.")
        sys.exit(1)

    n_treated = data.loc[data["is_treated"] == 1, "hero_key"].nunique()
    days = sorted(data["pulled_date"].astype(str).unique())
    print(f"Patch {patch_date}, {change_type}: {n_treated} treated heroes, "
          f"{len(days)} snapshot days ({days[0]} to {days[-1]})")

    for label, formula in [("Original DiD", BASE), ("With pre-trend control", WITH_TREND)]:
        model = fit(formula, data)
        est = model.params["is_treated:is_post"]
        p = model.pvalues["is_treated:is_post"]
        print(f"  {label:<24} effect = {est:+.2f}pp   p = {p:.4f}")

    gap = (
        data.groupby(["days_since_patch", "is_treated"])["pick_rate"].mean()
        .unstack()
        .rename(columns={0: "control", 1: "treated"})
    )
    gap["diff"] = gap["treated"] - gap["control"]

    os.makedirs("analysis/output", exist_ok=True)
    out = f"analysis/output/event_study_pick_rate_{change_type}_{patch_date}.png"
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(gap.index, gap["diff"], marker="o", linewidth=1.5)
    ax.axvline(0, color="red", linestyle="--", label="Patch day")
    ax.axhline(0, color="blue", linewidth=0.8)
    ax.set_title(f"Event study: treated - control pick rate ({change_type}, {patch_date})")
    ax.set_xlabel("Days since patch")
    ax.set_ylabel("pick_rate difference (pp)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print(f"Saved {out}")


if __name__ == "__main__":
    main(
        sys.argv[1] if len(sys.argv) > 1 else "2026-09-08",
        sys.argv[2] if len(sys.argv) > 2 else "nerf",
    )
