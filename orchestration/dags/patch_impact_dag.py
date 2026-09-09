"""
orchestration/dags/patch_impact_dag.py

Daily extract → load → dbt run → dbt test → causal analysis pipeline.

Dependency order enforced in the DAG:
  extract_hero_rates   extract_patch_notes
       │                     │
          load_to_bq
               │
           dbt_run
               │
           dbt_test
               │
        causal_analysis

dbt_test acts as a data-quality gate: if tests fail, causal_analysis is skipped.

No leaderboard/battletag collection step: Blizzard's official Hero
Statistics page (overwatch.blizzard.com/en-us/rates/) returns
population-level pick/win/ban rates directly, so there's no per-player
list to build or look up first -- extract_hero_rates and
extract_patch_notes are independent and run in parallel.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator

from extract.hero_rates_scraper import collect_all as collect_hero_rates
from extract.patch_notes_scraper import scrape_patch_notes
from load.bigquery_loader import get_client, load_csv_to_table

default_args = {
    "owner": "rachel",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="ow_patch_impact_daily",
    default_args=default_args,
    schedule_interval="0 6 * * *",  # daily at 06:00 UTC
    start_date=datetime(2026, 9, 1),
    catchup=False,
    tags=["overwatch", "etl", "causal-inference"],
) as dag:

    def _extract_hero_rates():
        df = collect_hero_rates()
        path = "data/raw/hero_rates/hero_rates_latest.csv"
        df.to_csv(path, index=False)
        return path

    def _extract_patch_notes():
        df = scrape_patch_notes()
        path = "data/raw/patch_notes/patch_events.csv"
        df.to_csv(path, index=False)
        return path

    def _load_to_bq(**context):
        client = get_client()
        hero_path = context["ti"].xcom_pull(task_ids="extract_hero_rates")
        patch_path = context["ti"].xcom_pull(task_ids="extract_patch_notes")
        load_csv_to_table(client, hero_path, "hero_rates")
        load_csv_to_table(client, patch_path, "patch_events")

    extract_hero_rates = PythonOperator(
        task_id="extract_hero_rates",
        python_callable=_extract_hero_rates,
    )

    extract_patch_notes = PythonOperator(
        task_id="extract_patch_notes",
        python_callable=_extract_patch_notes,
    )

    load_to_bq = PythonOperator(
        task_id="load_to_bq",
        python_callable=_load_to_bq,
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command="cd /opt/airflow/transform && dbt run --profiles-dir .",
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command="cd /opt/airflow/transform && dbt test --profiles-dir .",
    )

    causal_analysis = BashOperator(
        task_id="causal_analysis",
        bash_command="python -m analysis.did_analysis",
    )

    # extract_hero_rates and extract_patch_notes are independent -- no leaderboard
    # lookup step needed first -- so they run in parallel, then both load to BQ.
    [extract_hero_rates, extract_patch_notes] >> load_to_bq >> dbt_run >> dbt_test >> causal_analysis
