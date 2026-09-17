"""
analysis/event_study.py

Generates event-study plots to visually verify the parallel-trends assumption
required for DiD: before the patch, treated and control heroes should trend
together; only at day 0 should they diverge.

The plot shows (treated avg <outcome>) - (control avg <outcome>) by day,
centered on patch day = 0. Run for pick_rate, winrate, and ban_rate --
see analysis/did_analysis.py docstring for why all three are treated as
outcomes worth checking.
"""
import os

import matplotlib.pyplot as plt
import pandas as pd

from analysis.did_analysis import load_panel, scope_for_change_type


def build_event_study_series(df: pd.DataFrame, change_type: str, outcome: str = "pick_rate") -> pd.DataFrame:
    """Compute mean treated-minus-control outcome gap for each day relative to
    patch. Uses the same scoping as run_did (mixed buff+nerf heroes dropped,
    controls restricted to patch_date(s) with a real treated hero of this
    change_type) so this plot matches what the regression actually saw."""
    subset = scope_for_change_type(df, change_type)
    grouped = (
        subset.groupby(["days_since_patch", "is_treated"])[outcome]
        .mean()
        .reset_index()
    )
    pivoted = grouped.pivot(
        index="days_since_patch", columns="is_treated", values=outcome
    )
    pivoted.columns = ["control", "treated"]
    pivoted["diff"] = pivoted["treated"] - pivoted["control"]
    return pivoted


def plot_event_study(pivoted: pd.DataFrame, change_type: str, outcome: str, out_path: str):
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(pivoted.index, pivoted["diff"], marker="o", linewidth=1.5)
    ax.axvline(0, color="red", linestyle="--", label="Patch day")
    ax.axhline(0, color="blue", linewidth=0.8)
    ax.set_title(f"Event Study: Treated – Control {outcome} Gap ({change_type})")
    ax.set_xlabel("Days since patch")
    ax.set_ylabel(f"{outcome} difference (pp)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"Saved event-study plot: {out_path}")


if __name__ == "__main__":
    os.makedirs("analysis/output", exist_ok=True)
    panel = load_panel()
    for outcome in ["pick_rate", "winrate", "ban_rate"]:
        for change in ["buff", "nerf"]:
            series = build_event_study_series(panel, change, outcome=outcome)
            plot_event_study(
                series,
                change_type=change,
                outcome=outcome,
                out_path=f"analysis/output/event_study_{outcome}_{change}.png",
            )
