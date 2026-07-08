"""Migration: Add description and property_type columns to properties table.

Source: propertyvalue.co.nz testid='story-content' (About section) + property type section
Purpose: Enable Gemini AI qualitative analysis and richer frontend cards.
"""
import sys
import os
sys.path.append(os.getcwd())

from utils.database import db
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MIGRATIONS = [
    {
        "name": "add_description_column_properties",
        "check": """
            SELECT COUNT(*) AS cnt
            FROM information_schema.columns
            WHERE table_name = 'properties' AND column_name = 'description'
        """,
        "sql": "ALTER TABLE properties ADD COLUMN description TEXT",
    },
    {
        "name": "add_property_type_column_properties",
        "check": """
            SELECT COUNT(*) AS cnt
            FROM information_schema.columns
            WHERE table_name = 'properties' AND column_name = 'property_type'
        """,
        "sql": "ALTER TABLE properties ADD COLUMN property_type TEXT",
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
