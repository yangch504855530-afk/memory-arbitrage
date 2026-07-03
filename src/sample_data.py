from __future__ import annotations

import csv
from pathlib import Path

from db import DEFAULT_DB_PATH, delete_observations_by_source, insert_price_observation
from importer import import_products
from models import PriceObservation


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PRODUCTS_PATH = PROJECT_ROOT / "config" / "products.sample.yaml"
SAMPLE_PRICES_PATH = PROJECT_ROOT / "config" / "price_observations.sample.csv"


def load_sample_data(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, int]:
    products_count = import_products(SAMPLE_PRODUCTS_PATH, db_path=db_path)
    deleted_observations = delete_observations_by_source("sample", db_path=db_path)
    observations_count = 0

    with SAMPLE_PRICES_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            row["source"] = "sample"
            observation = PriceObservation.from_mapping(row)
            insert_price_observation(observation, db_path=db_path)
            observations_count += 1

    return {
        "products": products_count,
        "deleted_observations": deleted_observations,
        "observations": observations_count,
    }
