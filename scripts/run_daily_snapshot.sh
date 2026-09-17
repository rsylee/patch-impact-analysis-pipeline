#!/bin/bash
# scripts/run_daily_snapshot.sh
#
# Invoked daily by launchd (see ~/Library/LaunchAgents/com.rachellee.ow-hero-rates-daily.plist).
# Runs the hero-rates scraper, archives that day's snapshot to a dated file
# (hero_rates_scraper.py itself always overwrites hero_rates_latest.csv, so
# without this step every run would destroy the previous day's data),
# then attempts a BigQuery load only if GCP credentials are actually present
# -- logging clearly either way rather than failing silently.
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
LOG_FILE="$REPO_DIR/logs/hero_rates_daily.log"
DATE_STAMP="$(date +%Y-%m-%d)"
TIMESTAMP="$(date +"%Y-%m-%dT%H:%M:%S%z")"

mkdir -p "$REPO_DIR/logs" "$REPO_DIR/data/raw/hero_rates/history"

echo "[$TIMESTAMP] === starting daily hero rates run ===" >> "$LOG_FILE"

if "$PYTHON_BIN" -m extract.hero_rates_scraper >> "$LOG_FILE" 2>&1; then
    ARCHIVE_FILE="$REPO_DIR/data/raw/hero_rates/history/hero_rates_${DATE_STAMP}.csv"
    cp "$REPO_DIR/data/raw/hero_rates/hero_rates_latest.csv" "$ARCHIVE_FILE"
    echo "[$TIMESTAMP] scrape OK -- archived to data/raw/hero_rates/history/hero_rates_${DATE_STAMP}.csv" >> "$LOG_FILE"
else
    echo "[$TIMESTAMP] SCRAPE FAILED -- see output above for the error" >> "$LOG_FILE"
    echo "[$TIMESTAMP] === run finished (failure) ===" >> "$LOG_FILE"
    exit 1
fi

if "$PYTHON_BIN" -m extract.patch_notes_scraper >> "$LOG_FILE" 2>&1; then
    echo "[$TIMESTAMP] patch notes scrape OK -- data/raw/patch_notes/patch_events.csv refreshed" >> "$LOG_FILE"
else
    echo "[$TIMESTAMP] PATCH NOTES SCRAPE FAILED -- proceeding with hero-rates load anyway, patch_events.csv left at its last good state" >> "$LOG_FILE"
fi

if [ -f "$REPO_DIR/.env" ] && [ -f "$REPO_DIR/secrets/gcp-service-account.json" ]; then
    echo "[$TIMESTAMP] GCP credentials found -- attempting BigQuery load" >> "$LOG_FILE"
    if "$PYTHON_BIN" -m load.bigquery_loader >> "$LOG_FILE" 2>&1; then
        echo "[$TIMESTAMP] BigQuery load OK" >> "$LOG_FILE"
    else
        echo "[$TIMESTAMP] BigQuery load FAILED -- snapshot is still safe in data/raw/hero_rates/history/, just not in BQ yet" >> "$LOG_FILE"
    fi
else
    echo "[$TIMESTAMP] GCP not configured yet (.env or secrets/gcp-service-account.json missing) -- skipping BigQuery, snapshot saved locally only" >> "$LOG_FILE"
fi

echo "[$TIMESTAMP] === run finished ===" >> "$LOG_FILE"
