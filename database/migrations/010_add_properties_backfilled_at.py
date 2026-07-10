import sys
import os
sys.path.append(os.getcwd())
from utils.database import db

def run():
    db.execute("ALTER TABLE properties ADD COLUMN IF NOT EXISTS backfilled_at TIMESTAMPTZ DEFAULT NULL")
    db.execute("CREATE INDEX IF NOT EXISTS idx_properties_backfilled_at ON properties (backfilled_at) WHERE backfilled_at IS NULL")

if __name__ == "__main__":
    run()
