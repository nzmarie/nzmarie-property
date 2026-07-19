"""
Migration 011: Add last_sold_date and property_history columns to real_estate and real_estate_rent.
These are populated by the backfill_realestate scraper from the sale-history section on detail pages.
"""
import sys, os
sys.path.append(os.getcwd())
from utils.database import db
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MIGRATIONS = [
    {
        "name": "add_last_sold_date_to_real_estate",
        "sql": "ALTER TABLE real_estate ADD COLUMN IF NOT EXISTS last_sold_date DATE",
    },
    {
        "name": "add_property_history_to_real_estate",
        "sql": "ALTER TABLE real_estate ADD COLUMN IF NOT EXISTS property_history TEXT",
    },
    {
        "name": "add_last_sold_date_to_real_estate_rent",
        "sql": "ALTER TABLE real_estate_rent ADD COLUMN IF NOT EXISTS last_sold_date DATE",
    },
    {
        "name": "add_property_history_to_real_estate_rent",
        "sql": "ALTER TABLE real_estate_rent ADD COLUMN IF NOT EXISTS property_history TEXT",
    },
]

def run():
    for m in MIGRATIONS:
        try:
            db.execute(m["sql"])
            logger.info(f"✅ {m['name']}")
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.info(f"⏭  {m['name']} (already exists)")
            else:
                logger.error(f"❌ {m['name']}: {e}")
                raise

if __name__ == "__main__":
    run()
    logger.info("Migration 011 complete.")
