"""
Migration 012: Add breakpoint-resume columns to scraping_progress.

These columns let the property_value_engine persist:
  - which Territorial Authority (TA slug) is being scraped
  - the target suburb list and which suburbs are already done
  - how many properties remain to be backfilled

This enables reliable resume across the GitHub Actions 5.5h limit.
"""
import sys, os
sys.path.append(os.getcwd())
from utils.database import db
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MIGRATIONS = [
    {
        "name": "add_ta_slug_to_scraping_progress",
        "sql": "ALTER TABLE scraping_progress ADD COLUMN IF NOT EXISTS ta_slug TEXT",
    },
    {
        "name": "add_suburbs_target_to_scraping_progress",
        "sql": "ALTER TABLE scraping_progress ADD COLUMN IF NOT EXISTS suburbs_target TEXT",
    },
    {
        "name": "add_suburbs_completed_to_scraping_progress",
        "sql": "ALTER TABLE scraping_progress ADD COLUMN IF NOT EXISTS suburbs_completed TEXT",
    },
    {
        "name": "add_total_suburbs_to_scraping_progress",
        "sql": "ALTER TABLE scraping_progress ADD COLUMN IF NOT EXISTS total_suburbs INTEGER",
    },
    {
        "name": "add_completed_suburbs_to_scraping_progress",
        "sql": "ALTER TABLE scraping_progress ADD COLUMN IF NOT EXISTS completed_suburbs INTEGER",
    },
    {
        "name": "add_remaining_count_to_scraping_progress",
        "sql": "ALTER TABLE scraping_progress ADD COLUMN IF NOT EXISTS remaining_count INTEGER",
    },
]

def run():
    for m in MIGRATIONS:
        try:
            db.execute(m["sql"])
            logger.info(f"OK {m['name']}")
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.info(f"SKIP {m['name']} (already exists)")
            else:
                logger.error(f"FAIL {m['name']}: {e}")
                raise

if __name__ == "__main__":
    run()
    logger.info("Migration 012 complete.")