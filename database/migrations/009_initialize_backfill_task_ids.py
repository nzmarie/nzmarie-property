import sys
import os
sys.path.append(os.getcwd())
from utils.database import db

def run():
    tasks = [
        (14, 'Auckland Backfill'),
        (15, 'Wellington Backfill'),
        (16, 'Auckland Suburbs Backfill'),
        (17, 'Wellington Suburbs Backfill')
    ]
    for task_id, desc in tasks:
        db.execute(
            "UPSERT INTO scraping_progress (id, status, description, updated_at) VALUES (%s, 'idle', %s, NOW())",
            (task_id, desc)
        )

if __name__ == "__main__":
    run()
