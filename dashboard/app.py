"""
dashboard/app.py

Streamlit dashboard: "Which heroes actually got stronger after this patch?"
Reads from BigQuery mart tables; caches data for 1 hour to avoid repeated queries.
"""
import pandas as pd
import streamlit as st

from load.bigquery_loader import get_client

st.set_page_config(page_title="OW Patch Impact Dashboard", layout="wide")

PROJECT_ID = "ow-patch-impact"


@st.cache_data(ttl=3600)
def load_daily_stats() -> pd.DataFrame:
    client = get_client()
    query = f"SELECT * FROM `{PROJECT_ID}.ow_marts.mart_hero_stats_daily`"
    return client.query(query).to_dataframe()


st.title("Overwatch Patch Impact Dashboard")

df = load_daily_stats()

col1, col2, col3 = st.columns(3)
with col1:
    region = st.selectbox("Region", sorted(df["region"].unique()))
with col2:
    rank = st.selectbox("Rank Tier", sorted(df["rank_tier"].unique()))
with col3:
    role = st.selectbox("Role", sorted(df["role"].unique()))

filtered = df[(df["region"] == region) & (df["rank_tier"] == rank) & (df["role"] == role)]

st.subheader(f"Pick Rate Trend — {role.title()} / {rank.title()} / {region}")
pivot = filtered.pivot(index="pulled_date", columns="hero_key", values="avg_pick_rate")
st.line_chart(pivot)

st.subheader("Win Rate Trend")
pivot_wr = filtered.pivot(index="pulled_date", columns="hero_key", values="avg_winrate")
st.line_chart(pivot_wr)

st.subheader("Ban Rate Trend")
pivot_br = filtered.pivot(index="pulled_date", columns="hero_key", values="avg_ban_rate")
st.line_chart(pivot_br)

st.subheader("Latest Snapshot")
latest_date = filtered["pulled_date"].max()
snapshot = (
    filtered[filtered["pulled_date"] == latest_date]
    .sort_values("avg_pick_rate", ascending=False)
)
st.dataframe(
    snapshot[["hero_key", "avg_pick_rate", "avg_winrate", "avg_ban_rate"]],
    use_container_width=True,
)
