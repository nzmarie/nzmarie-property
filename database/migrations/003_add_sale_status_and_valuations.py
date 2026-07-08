"""Migration: Add sale_status and valuation columns to properties table.

Purpose: Enable cross-table address matching (properties <-> real_estate / real_estate_rent)
and store enhanced PropertyValue detail page data for sale prediction.

sale_status values: 'for_sale' | 'for_rent' | 'sold' | 'off_market' | 'unknown'
"""
import sys
import os
sys.path.append(os.getcwd())

from utils.database import db
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MIGRATIONS = [
    # --- Sale Status Tracking ---
    {
        "name": "add_sale_status_column",
        "check": """
            SELECT COUNT(*) AS cnt
            FROM information_schema.columns
            WHERE table_name = 'properties' AND column_name = 'sale_status'
        """,
        "sql": "ALTER TABLE properties ADD COLUMN sale_status VARCHAR(50) DEFAULT 'unknown'",
    },
    {
        "name": "add_sale_status_source_column",
        "check": """
            SELECT COUNT(*) AS cnt
            FROM information_schema.columns
            WHERE table_name = 'properties' AND column_name = 'sale_status_source'
        """,
        "sql": "ALTER TABLE properties ADD COLUMN sale_status_source VARCHAR(255)",
    },
    {
        "name": "add_sale_status_updated_at_column",
        "check": """
            SELECT COUNT(*) AS cnt
            FROM information_schema.columns
            WHERE table_name = 'properties' AND column_name = 'sale_status_updated_at'
        """,
        "sql": "ALTER TABLE properties ADD COLUMN sale_status_updated_at TIMESTAMPTZ",
    },
    # --- Enhanced PropertyValue Detail Fields ---
    {
        "name": "add_estimated_value_low_column",
        "check": """
            SELECT COUNT(*) AS cnt
            FROM information_schema.columns
            WHERE table_name = 'properties' AND column_name = 'estimated_value_low'
        """,
        "sql": "ALTER TABLE properties ADD COLUMN estimated_value_low DOUBLE PRECISION",
    },
    {
        "name": "add_estimated_value_high_column",
        "check": """
            SELECT COUNT(*) AS cnt
            FROM information_schema.columns
            WHERE table_name = 'properties' AND column_name = 'estimated_value_high'
        """,
        "sql": "ALTER TABLE properties ADD COLUMN estimated_value_high DOUBLE PRECISION",
    },
    # Note: last_sold_price and last_sold_date already exist in schema, skip adding them
    {
        "name": "add_suburb_median_price_column",
        "check": """
            SELECT COUNT(*) AS cnt
            FROM information_schema.columns
            WHERE table_name = 'properties' AND column_name = 'suburb_median_price'
        """,
        "sql": "ALTER TABLE properties ADD COLUMN suburb_median_price DOUBLE PRECISION",
    },
    {
        "name": "add_suburb_median_rent_column",
        "check": """
            SELECT COUNT(*) AS cnt
            FROM information_schema.columns
            WHERE table_name = 'properties' AND column_name = 'suburb_median_rent'
        """,
        "sql": "ALTER TABLE properties ADD COLUMN suburb_median_rent DOUBLE PRECISION",
    },
    {
        "name": "add_suburb_days_on_market_column",
        "check": """
            SELECT COUNT(*) AS cnt
            FROM information_schema.columns
            WHERE table_name = 'properties' AND column_name = 'suburb_days_on_market'
        """,
        "sql": "ALTER TABLE properties ADD COLUMN suburb_days_on_market INTEGER",
    },
    # --- Index for faster status lookups ---
    {
        "name": "add_sale_status_index",
        "check": """
            SELECT COUNT(*) AS cnt
            FROM pg_indexes
            WHERE tablename = 'properties' AND indexname = 'idx_properties_sale_status'
        """,
        "sql": "CREATE INDEX idx_properties_sale_status ON properties (sale_status)",
    },
]


def run():
    for m in MIGRATIONS:
        name = m["name"]
        if m.get("check"):
            try:
                res = db.query(m["check"])
                cnt = res[0]['cnt'] if res else 0
                if cnt > 0:
                    logger.info(f"[SKIP] '{name}' already applied.")
                    continue
            except Exception as e:
                logger.warning(f"Check failed for '{name}': {e}")

        try:
            db.execute(m["sql"])
            logger.info(f"[OK] Applied migration: {name}")
        except Exception as e:
            logger.error(f"[FAIL] Migration '{name}': {e}")


if __name__ == "__main__":
    run()
