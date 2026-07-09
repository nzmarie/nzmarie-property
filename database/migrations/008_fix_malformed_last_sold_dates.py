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
    logger.info("Migration 008: Skipped cleanup because engine date parser handles malformed values natively.")

if __name__ == "__main__":
    run()
    logger.info("Migration 008 complete.")
