"""
extract/kaggle_loader.py

This script downloads the Kaggle Overwatch League dataset for supplementary validation:
comparing ladder meta (Blizzard's Hero Statistics page) with pro-play meta (OWL).
(requires KAGGLE_USERNAME and KAGGLE_KEY in .env. -> NEED TO SET UP THIS)
"""
import os
from kaggle.api.kaggle_api_extended import KaggleApi

# NOTE: Verify this dataset slug is still active before running.
# Search kaggle.com/datasets for current OWL match data if this returns 404.
DATASET_SLUG = "eddieafework/overwatch-league-stats"
OUT_DIR = "data/raw/owl"


def download_owl_dataset():
    api = KaggleApi()
    api.authenticate()
    os.makedirs(OUT_DIR, exist_ok=True)
    api.dataset_download_files(DATASET_SLUG, path=OUT_DIR, unzip=True)
    print(f"Downloaded OWL dataset to {OUT_DIR}")


if __name__ == "__main__":
    download_owl_dataset()
