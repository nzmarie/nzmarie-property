"""
Migration 007: Add description and listing_number to real_estate and real_estate_rent.

description    — full property listing text from [data-test="description-content__description"]
listing_number — listing ID from [data-test="description__listing-number"], e.g. "5616243652"
listing_date   — parsed DATE from listing_date_raw (already stored as raw text)
"""
import sys, os
sys.path.append(os.getcwd())
from utils.database import db
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MIGRATIONS = [
    {
        "name": "add_description_to_real_estate",
        "sql": "ALTER TABLE real_estate ADD COLUMN IF NOT EXISTS description TEXT",
    },
    {
        "name": "add_description_to_real_estate_rent",
        "sql": "ALTER TABLE real_estate_rent ADD COLUMN IF NOT EXISTS description TEXT",
    },
    {
        "name": "add_listing_number_to_real_estate",
        "sql": "ALTER TABLE real_estate ADD COLUMN IF NOT EXISTS listing_number TEXT",
    },
    {
        "name": "add_listing_number_to_real_estate_rent",
        "sql": "ALTER TABLE real_estate_rent ADD COLUMN IF NOT EXISTS listing_number TEXT",
    },
    {
        "name": "add_listing_date_parsed_to_real_estate",
        "sql": "ALTER TABLE real_estate ADD COLUMN IF NOT EXISTS listing_date_parsed DATE",
    },
    {
        "name": "add_listing_date_parsed_to_real_estate_rent",
        "sql": "ALTER TABLE real_estate_rent ADD COLUMN IF NOT EXISTS listing_date_parsed DATE",
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
    logger.info("Migration 007 complete.")
