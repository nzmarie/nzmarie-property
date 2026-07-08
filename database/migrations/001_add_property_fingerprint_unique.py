import sys
import os
sys.path.append(os.getcwd())

from utils.database import db
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MIGRATIONS = [
    {
        "name": "add_unique_index_properties_fingerprint",
        "check": """
            SELECT COUNT(*) AS cnt 
            FROM information_schema.key_column_usage kcu
            JOIN information_schema.table_constraints tc ON kcu.constraint_name = tc.constraint_name
            WHERE kcu.table_name = 'properties' 
              AND kcu.column_name = 'address_fingerprint'
              AND tc.constraint_type = 'UNIQUE'
        """,
        "sql": "CREATE UNIQUE INDEX IF NOT EXISTS uq_properties_address_fingerprint ON properties (address_fingerprint) WHERE address_fingerprint IS NOT NULL",
    },
    {
        "name": "deduplicate_properties_fingerprint",
        "check": None,
        "sql": """
            DELETE FROM properties
            WHERE id NOT IN (
                SELECT MIN(id) FROM properties
                WHERE address_fingerprint IS NOT NULL
                GROUP BY address_fingerprint
            )
            AND address_fingerprint IS NOT NULL
        """,
        "run_before": "add_unique_index_properties_fingerprint",
    },
]

def run():
    logger.info("Running database migrations...")

    dedup = next((m for m in MIGRATIONS if m["name"] == "deduplicate_properties_fingerprint"), None)
    if dedup:
        try:
            logger.info(f"Running: {dedup['name']}")
            db.execute(dedup["sql"])
            logger.info(f"Done: {dedup['name']}")
        except Exception as e:
            logger.warning(f"Skipped {dedup['name']}: {e}")

    for migration in MIGRATIONS:
        if migration.get("run_before"):
            continue

        name = migration["name"]
        check_sql = migration.get("check")

        if check_sql:
            try:
                result = db.query(check_sql)
                if result and result[0].get("cnt", 0) > 0:
                    logger.info(f"Already applied: {name}")
                    continue
            except Exception as e:
                logger.warning(f"Check failed for {name}: {e}")

        try:
            logger.info(f"Applying: {name}")
            db.execute(migration["sql"])
            logger.info(f"Applied: {name}")
        except Exception as e:
            logger.error(f"Failed to apply {name}: {e}")

    logger.info("Migrations complete.")

if __name__ == "__main__":
    run()
