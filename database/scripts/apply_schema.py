import os
import sys
from pathlib import Path

sys.path.append(os.getcwd())

from utils.database import db


def load_sql_statements(schema_path: str):
    sql_text = Path(schema_path).read_text(encoding="utf-8")
    statements = []
    for stmt in sql_text.split(";"):
        cleaned = stmt.strip()
        if not cleaned or cleaned.startswith("--"):
            continue
        statements.append(cleaned)
    return statements


def apply_schema(schema_path: str = "database/schema/full_schema.sql"):
    statements = load_sql_statements(schema_path)
    applied = 0
    for statement in statements:
        try:
            db.execute(statement)
            applied += 1
        except Exception as exc:
            print(f"Skipped statement due to error: {exc}")
    print(f"Applied {applied} schema statements from {schema_path}")
    return applied


if __name__ == "__main__":
    apply_schema()
