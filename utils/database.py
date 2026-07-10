import os
import urllib.parse
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from sqlalchemy import create_engine

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - exercised in CI when pandas is missing
    pd = None

load_dotenv()

class DatabaseClient:
    def __init__(self):
        database_url = os.getenv("DATABASE_URL")
        parsed_url = None
        if database_url:
            parsed_url = urllib.parse.urlparse(database_url)

        # 1. Load base credentials
        base_user = os.getenv("COCKROACH_USER") or os.getenv("SQL-user") or "nzmarie"
        self.password = os.getenv("COCKROACH_PASSWORD") or os.getenv("SQL-user-password")
        self.host = os.getenv("COCKROACH_HOST") or os.getenv("SQL-host")
        self.port = os.getenv("COCKROACH_PORT") or os.getenv("SQL-port")
        self.dbname = os.getenv("COCKROACH_DB") or os.getenv("COCKROACH_DBNAME") or os.getenv("SQL-dbname")

        if parsed_url and parsed_url.hostname:
            self.host = self.host or parsed_url.hostname
            self.port = self.port or str(parsed_url.port or 26257)
            self.dbname = self.dbname or parsed_url.path.lstrip("/") or "defaultdb"
            if not self.password:
                self.password = parsed_url.password or ""
            self.user = parsed_url.username or base_user
        else:
            self.host = self.host or "baby-centaur-27756.j77.aws-ap-southeast-1.cockroachlabs.cloud"
            self.port = self.port or "26257"
            self.dbname = self.dbname or "defaultdb"
            self.user = base_user

        # 2. Keep the username in the same format used by the working DATABASE_URL.
        # CockroachDB Cloud accepts the plain username from the environment.

        # 4. Handle SQLAlchemy (URI format) - use explicit cockroachdb:// with sslmode=require
        self.conn_str = f"cockroachdb://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}?sslmode=require"

        # 5. Handle psycopg2 DSN (Key-Value) - use explicit postgresql:// with sslmode=require
        self.psycopg2_dsn = f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}?sslmode=require"

        import sys
        print(f"Database initialized. User: {self.user}, Host: {self.host}", file=sys.stderr)
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = create_engine(self.conn_str)
        return self._engine

    def get_connection(self):
        # Use keyword arguments for psycopg2 to handle special characters properly
        return psycopg2.connect(
            user=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            sslmode='require'
        )

    def query(self, sql, params=None):
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                if cur.description:
                    return cur.fetchall()
                return None

    def read_df(self, table_or_sql):
        if pd is None:
            raise ModuleNotFoundError("pandas is required for read_df(). Please install pandas to use this helper.")
        return pd.read_sql(table_or_sql, self.conn_str)

    def execute(self, sql, params=None):
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()

    def execute_batch(self, sql, params_list):
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, sql, params_list)
            conn.commit()

db = DatabaseClient()

def get_db():
    return db
