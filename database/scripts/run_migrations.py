import os
import sys
import importlib.util
import logging

sys.path.append(os.getcwd())
from utils.database import db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run():
    logger.info("Initializing migrations table...")
    db.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_id VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    migrations_dir = "database/migrations"
    if not os.path.exists(migrations_dir):
        logger.info("No migrations directory found.")
        return
        
    files = sorted([f for f in os.listdir(migrations_dir) if f.endswith(".py")])
    for f in files:
        exists = db.query("SELECT 1 FROM schema_migrations WHERE migration_id = %s", (f,))
        if exists:
            logger.info(f"Migration {f} already applied.")
            continue
            
        logger.info(f"Applying migration: {f}")
        module_name = f[:-3]
        spec = importlib.util.spec_from_file_location(module_name, os.path.join(migrations_dir, f))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        if hasattr(module, "run"):
            module.run()
            
        db.execute("INSERT INTO schema_migrations (migration_id) VALUES (%s)", (f,))
        logger.info(f"Migration {f} applied successfully.")

if __name__ == "__main__":
    run()
