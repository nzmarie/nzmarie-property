"""
Migration 008: Fix malformed last_sold_date values in properties table.

Problem: Some records have non-ISO date formats (bare years like "2024") that CockroachDB
cannot parse. This causes UPDATE failures during backfill.

Solution: Clear all last_sold_date values so backfill can repopulate them correctly.
This is safe because backfill will re-scrape and set proper dates.
"""
import sys, os
sys.path.append(os.getcwd())
from utils.database import db
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run():
    try:
        # Check if last_sold_date column exists
        sql_check = """
            SELECT COUNT(*) as cnt FROM properties 
            WHERE last_sold_date IS NOT NULL LIMIT 1
        """
        try:
            db.query(sql_check)
        except Exception as e:
            if "does not exist" in str(e).lower() or "column" in str(e).lower():
                logger.info("⏭️  Migration 008: last_sold_date column doesn't exist yet")
                return
            raise

        # Count how many NULL vs non-NULL dates exist
        sql_count = """
            SELECT 
                COUNT(*) FILTER (WHERE last_sold_date IS NULL) as null_count,
                COUNT(*) FILTER (WHERE last_sold_date IS NOT NULL) as non_null_count
            FROM properties
        """
        result = db.query(sql_count)
        null_cnt = result[0]['null_count'] if result else 0
        non_null_cnt = result[0]['non_null_count'] if result else 0
        logger.info(f"Before cleanup: NULL dates={null_cnt}, non-NULL dates={non_null_cnt}")

        # Clear ALL last_sold_date values to fix malformed dates
        # Backfill will re-scrape and populate with correct values
        sql_clear = "UPDATE properties SET last_sold_date = NULL"
        db.execute(sql_clear)
        logger.info(f"✅ Migration 008: Cleared {non_null_cnt} last_sold_date values (will be repopulated by backfill)")
        
    except Exception as e:
        logger.error(f"❌ Migration 008 failed: {e}")
        raise

if __name__ == "__main__":
    run()
    logger.info("Migration 008 complete.")
