"""
Migration 006: Add property_type and floor_area columns to real_estate and real_estate_rent tables.
These are populated by the realestate.co.nz scraper from the features-icons section.
"""
import sys, os
sys.path.append(os.getcwd())
from utils.database import db
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MIGRATIONS = [
    {
        "name": "add_property_type_to_real_estate",
        "sql": "ALTER TABLE real_estate ADD COLUMN IF NOT EXISTS property_type TEXT",
    },
    {
        "name": "add_property_type_to_real_estate_rent",
        "sql": "ALTER TABLE real_estate_rent ADD COLUMN IF NOT EXISTS property_type TEXT",
    },
    {
        "name": "add_cover_image_url_to_real_estate",
        "sql": "ALTER TABLE real_estate ADD COLUMN IF NOT EXISTS cover_image_url TEXT",
    },
    {
        "name": "add_cover_image_url_to_real_estate_rent",
        "sql": "ALTER TABLE real_estate_rent ADD COLUMN IF NOT EXISTS cover_image_url TEXT",
    },
    {
        "name": "add_images_to_real_estate",
        "sql": "ALTER TABLE real_estate ADD COLUMN IF NOT EXISTS images JSONB",
    },
    {
        "name": "add_images_to_real_estate_rent",
        "sql": "ALTER TABLE real_estate_rent ADD COLUMN IF NOT EXISTS images JSONB",
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
    logger.info("Migration 006 complete.")
