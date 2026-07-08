import os
import sys

sys.path.append(os.getcwd())
from utils.database import db

def run():
    schema_path = os.path.join("database", "schema", "full_schema.sql")
    if not os.path.exists(schema_path):
        print(f"Schema file not found at {schema_path}")
        return

    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()

    print("Initializing database schema...")
    try:
        db.execute(sql)
        print("Database schema initialized successfully.")
    except Exception as e:
        print(f"Failed to initialize database: {e}")

if __name__ == "__main__":
    run()
