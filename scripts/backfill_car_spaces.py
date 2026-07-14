"""
Backfill car_spaces for real_estate and real_estate_rent tables.

Extracts Garage count from features-icons section on detail pages
and updates car_spaces column where currently NULL.

Usage:
    python scripts/backfill_car_spaces.py [--table real_estate] [--limit 100] [--max-runtime 3]

Tables supported:
    real_estate      — has property_url for all 1435 records → full backfill possible
    real_estate_rent — only 2 records have property_url → partial backfill
"""
import sys, os, time, random, re, json, argparse, logging
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from utils.database import db

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_records_to_backfill(table, limit=None):
    """Get records with NULL car_spaces and a valid property_url."""
    sql = f"SELECT id, property_url, address, suburb, city FROM {table} WHERE car_spaces IS NULL AND property_url IS NOT NULL"
    params = []
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    return db.query(sql, params) or []


def extract_garage_from_page(page, url):
    """Visit detail page and extract Garage count from features-icons."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(1.5, 3))
        try:
            page.wait_for_selector('div[data-test="features-icons"]', timeout=8000)
        except Exception:
            return None

        result = page.evaluate("""
            () => {
                const container = document.querySelector('div[data-test="features-icons"]');
                if (!container) return null;
                const items = container.querySelectorAll(':scope > div');
                let total = 0;
                let found = false;
                for (const item of items) {
                    const titleEl = item.querySelector('svg title');
                    const span = item.querySelector('span');
                    if (!titleEl || !span) continue;
                    const label = titleEl.textContent.trim();
                    if (label === 'Garage' || label === 'Other park') {
                        const val = parseInt(span.textContent.trim(), 10);
                        if (!isNaN(val)) {
                            total += val;
                            found = true;
                        }
                    }
                }
                return found ? total : null;
            }
        """)
        return result
    except Exception as e:
        logger.warning(f"Error extracting garage from {url}: {e}")
        return None


def update_car_spaces(table, record_id, car_spaces):
    """Update car_spaces for a given record."""
    try:
        db.execute(
            f"UPDATE {table} SET car_spaces = %s WHERE id = %s",
            (car_spaces, record_id)
        )
        return True
    except Exception as e:
        logger.error(f"Failed to update {table} id={record_id}: {e}")
        return False


def backfill(table, limit=None, max_runtime_hours=3):
    records = get_records_to_backfill(table, limit)
    total = len(records)
    logger.info(f"Found {total} records with NULL car_spaces in {table}")

    if total == 0:
        print(f"[OK] {table}: No records need backfill (car_spaces already filled or no URLs)")
        return

    start_time = time.time()
    max_seconds = max_runtime_hours * 3600
    updated = 0
    skipped = 0
    errors = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = context.new_page()

        for i, rec in enumerate(records):
            elapsed = time.time() - start_time
            if elapsed > max_seconds:
                logger.info(f"Max runtime ({max_runtime_hours}h) reached. Stopped at {i}/{total}")
                break

            rid = rec['id']
            url = rec['property_url']
            addr = rec['address']
            sub = rec.get('suburb') or ''
            ci = rec.get('city') or ''
            logger.info(f"[{i+1}/{total}] {addr}, {sub}, {ci}")

            car = extract_garage_from_page(page, url)
            if car is not None:
                if update_car_spaces(table, rid, car):
                    updated += 1
                    print(f"  [OK] car_spaces={car}")
                else:
                    errors += 1
            else:
                skipped += 1
                print("  [SKIP] no garage data found")

            if i < total - 1:
                time.sleep(random.uniform(1, 2))

        browser.close()

    duration = (time.time() - start_time) / 60
    print(f"\n{'='*50}")
    print(f"Table: {table}")
    print(f"  Processed: {i+1}/{total}")
    print(f"  Updated:   {updated}")
    print(f"  Skipped:   {skipped}")
    print(f"  Errors:    {errors}")
    print(f"  Duration:  {duration:.1f} min")
    print(f"{'='*50}")


def main():
    parser = argparse.ArgumentParser(description="Backfill car_spaces from detail pages")
    parser.add_argument("--table", choices=["real_estate", "real_estate_rent", "all"],
                        default="all", help="Table to backfill")
    parser.add_argument("--limit", type=int, help="Max records to process")
    parser.add_argument("--max-runtime", type=float, default=3, help="Max runtime in hours")
    args = parser.parse_args()

    tables = ["real_estate", "real_estate_rent"] if args.table == "all" else [args.table]
    for t in tables:
        backfill(t, limit=args.limit, max_runtime_hours=args.max_runtime)
        print()


if __name__ == "__main__":
    main()
