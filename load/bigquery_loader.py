"""
load/bigquery_loader.py

This script loads local raw CSVs into BigQuery raw dataset (ow_raw).
Uses WRITE_APPEND so each daily run accumulates a time-series of snapshots.
"""
import os
import logging

from google.cloud import bigquery
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_RAW = os.getenv("BQ_DATASET_RAW", "ow_raw")
SERVICE_ACCOUNT_JSON = os.getenv("GCP_SERVICE_ACCOUNT_JSON")


def get_client() -> bigquery.Client:
    if SERVICE_ACCOUNT_JSON:
        credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_JSON)
        return bigquery.Client(project=PROJECT_ID, credentials=credentials)
    return bigquery.Client(project=PROJECT_ID)


# Explicit schemas -- autodetect infers a fresh schema from each day's CSV in
# isolation (not from the existing table), so a column that happens to be
# all-whole-numbers on a given day (e.g. banrate=0 for every hero) gets
# guessed as INTEGER and breaks WRITE_APPEND against the FLOAT column from
# every other day.
TABLE_SCHEMAS = {
    "hero_rates": [
        bigquery.SchemaField("pulled_at", "TIMESTAMP"),
        bigquery.SchemaField("region", "STRING"),
        bigquery.SchemaField("tier", "STRING"),
        bigquery.SchemaField("hero_key", "STRING"),
        bigquery.SchemaField("hero_name", "STRING"),
        bigquery.SchemaField("role", "STRING"),
        bigquery.SchemaField("subrole", "STRING"),
        bigquery.SchemaField("winrate", "FLOAT64"),
        bigquery.SchemaField("pickrate", "FLOAT64"),
        bigquery.SchemaField("banrate", "FLOAT64"),
    ],
    "patch_events": [
        bigquery.SchemaField("patch_date", "DATE"),
        bigquery.SchemaField("hero_key", "STRING"),
        bigquery.SchemaField("change_text", "STRING"),
        bigquery.SchemaField("stat_name", "STRING"),
        bigquery.SchemaField("change_type", "STRING"),
        bigquery.SchemaField("magnitude", "FLOAT64"),
        bigquery.SchemaField("magnitude_unit", "STRING"),
        bigquery.SchemaField("review_needed", "BOOLEAN"),
    ],
}


def load_csv_to_table(client: bigquery.Client, csv_path: str, table_name: str, write_disposition=bigquery.WriteDisposition.WRITE_APPEND):
    table_id = f"{PROJECT_ID}.{DATASET_RAW}.{table_name}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        schema=TABLE_SCHEMAS[table_name],
        write_disposition=write_disposition,
    )
    with open(csv_path, "rb") as f:
        job = client.load_table_from_file(f, table_id, job_config=job_config)
    job.result()  # wait for completion
    logger.info(f"Loaded {csv_path} -> {table_id} ({job.output_rows} rows)")


if __name__ == "__main__":
    client = get_client()
    # hero_rates_latest.csv is a new daily snapshot -> append to build a time series
    load_csv_to_table(client, "data/raw/hero_rates/hero_rates_latest.csv", "hero_rates")
    # patch_events.csv is a full re-scrape of the patch notes page each run, not an
    # incremental delta -> truncate and replace, or every run would duplicate history
    load_csv_to_table(
        client, "data/raw/patch_notes/patch_events.csv", "patch_events",
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
