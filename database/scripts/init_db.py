import os
import urllib.parse
import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_cockroach_conn():
    database_url = os.getenv("DATABASE_URL")
    parsed_url = urllib.parse.urlparse(database_url) if database_url else None

    user = os.getenv("COCKROACH_USER") or os.getenv("SQL-user") or "nzmarie"
    password = os.getenv("COCKROACH_PASSWORD") or os.getenv("SQL-user-password")
    host = os.getenv("COCKROACH_HOST") or os.getenv("SQL-host")
    port = os.getenv("COCKROACH_PORT") or os.getenv("SQL-port") or "26257"
    dbname = os.getenv("COCKROACH_DB") or os.getenv("COCKROACH_DBNAME") or os.getenv("SQL-dbname") or "defaultdb"

    if parsed_url and parsed_url.hostname:
        host = host or parsed_url.hostname
        port = port or str(parsed_url.port or 26257)
        dbname = dbname or parsed_url.path.lstrip("/") or "defaultdb"
        if not password:
            password = parsed_url.password or ""
        if parsed_url.username:
            user = parsed_url.username

    host = host or "baby-centaur-27756.j77.aws-ap-southeast-1.cockroachlabs.cloud"

    return psycopg2.connect(
        user=user,
        password=password,
        host=host,
        port=port,
        dbname=dbname,
        sslmode='require',
    )

def run_sql_file(filepath):
    
    print(f"Executing {filepath}...")
    try:
        conn = get_cockroach_conn()
        conn.autocommit = True
        cur = conn.cursor()
        
        with open(filepath, 'r', encoding='utf-8') as f:
            sql = f.read()
            cur.execute(sql)
            
        cur.close()
        conn.close()
        print(f"  Success!")
    except Exception as e:
        print(f"  Error: {e}")

if __name__ == "__main__":
    run_sql_file(r"c:\Projects\nzmarieWorkspace\nzmarie-property\database\schema\01_tables.sql")
    run_sql_file(r"c:\Projects\nzmarieWorkspace\nzmarie-property\database\views\02_views.sql")
