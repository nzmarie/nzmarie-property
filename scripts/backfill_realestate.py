"""
Backfill property_history and last_sold_date for real_estate and real_estate_rent tables.

Extracts property history from the sale-history section on realestate.co.nz detail pages
and updates property_history (JSON) and last_sold_date columns where currently NULL.

Features:
  - Processes records until max_runtime is reached (supports breakpoint resume)
  - Automatically sets scraping_progress to 'complete' when no records remain
  - Idempotent: already-backfilled records are skipped (WHERE property_history IS NULL)
  - Compatible with gh_lock_manager workflow for concurrent-run safety

Usage:
    python scripts/backfill_realestate.py [--table real_estate] [--limit 100] [--max-runtime 5] [--task-id 7]

Tables supported:
    real_estate      — buy listings with property_url
    real_estate_rent — rent listings with property_url
"""
import sys, os, time, random, json, argparse, logging
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from utils.database import db

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_records_to_backfill(table, limit=None):
    """Get records with NULL property_history and a valid property_url."""
    sql = f"SELECT id, property_url, address, suburb, city FROM {table} WHERE property_history IS NULL AND property_url IS NOT NULL ORDER BY id"
    params = []
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    return db.query(sql, params) or []


def count_remaining(table):
    """Count how many records still need backfill."""
    rows = db.query(
        f"SELECT COUNT(*) AS cnt FROM {table} WHERE property_history IS NULL AND property_url IS NOT NULL"
    )
    return rows[0]['cnt'] if rows else 0


def parse_property_history(page, url):
    """Visit detail page and extract property history from sale-history rows.

    Returns (events_list, last_sold_date_str_or_None).
    Each event: {"date": str, "type": str, "value": str, "metadata": str}
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(1.5, 3))

        try:
            page.wait_for_selector('div[data-test="sale-history-row"]', timeout=10000)
        except Exception:
            pass

        rows = page.query_selector_all('div[data-test="sale-history-row"]')
        if not rows:
            logger.info(f"  No sale-history rows found on page")
            return [], None

        events = []
        last_sold = None
        last_sold_dt = None

        for row in rows:
            lis = row.query_selector_all('li')
            if len(lis) < 3:
                continue

            date_text = lis[0].inner_text().strip()
            type_text = lis[2].inner_text().strip()
            value_text = lis[3].inner_text().strip() if len(lis) >= 4 else ""
            meta_text = lis[4].inner_text().strip() if len(lis) >= 5 else ""

            event = {
                "date": date_text,
                "type": type_text,
                "value": value_text,
                "metadata": meta_text,
            }
            events.append(event)

            if type_text.lower() == "sold":
                try:
                    dt = datetime.strptime(date_text, "%d %b %Y")
                    if last_sold_dt is None or dt > last_sold_dt:
                        last_sold_dt = dt
                        last_sold = dt.strftime("%Y-%m-%d")
                except (ValueError, IndexError):
                    pass

        property_history = json.dumps(events, ensure_ascii=False) if events else "[]"
        return property_history, last_sold

    except Exception as e:
        logger.warning(f"Error parsing property history from {url}: {e}")
        return None, None


def update_record(table, record_id, property_history, last_sold_date):
    """Update property_history and last_sold_date for a given record."""
    try:
        db.execute(
            f"UPDATE {table} SET property_history = %s, last_sold_date = %s WHERE id = %s",
            (property_history, last_sold_date, record_id),
        )
        return True
    except Exception as e:
        logger.error(f"Failed to update {table} id={record_id}: {e}")
        return False


def set_task_complete(task_id):
    """Set scraping_progress status to 'complete'."""
    try:
        db.execute(
            "UPDATE scraping_progress SET status = 'complete', updated_at = NOW() WHERE id = %s",
            (task_id,),
        )
        logger.info(f"Task {task_id} marked as complete.")
    except Exception as e:
        logger.error(f"Failed to set task {task_id} complete: {e}")


def backfill(table, limit=None, max_runtime_hours=5, task_id=None):
    remaining = count_remaining(table)
    logger.info(f"Backfilling {table}: {remaining} records need property_history")

    if remaining == 0:
        print(f"[OK] {table}: No records need backfill (property_history already filled or no URLs)")
        if task_id:
            set_task_complete(task_id)
        return

    records = get_records_to_backfill(table, limit)
    total = len(records)
    logger.info(f"Fetched {total} records for processing")

    start_time = time.time()
    max_seconds = max_runtime_hours * 3600
    updated = 0
    skipped = 0
    errors = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page = context.new_page()

        for i, rec in enumerate(records):
            elapsed = time.time() - start_time
            if elapsed > max_seconds:
                logger.info(f"Max runtime ({max_runtime_hours}h) reached. Stopped at {i}/{total}")
                break

            rid = rec["id"]
            url = rec["property_url"]
            addr = rec["address"]
            sub = rec.get("suburb") or ""
            ci = rec.get("city") or ""
            logger.info(f"[{i+1}/{total}] {addr}, {sub}, {ci}")

            property_history, last_sold_date = parse_property_history(page, url)

            if property_history is not None:
                if update_record(table, rid, property_history, last_sold_date):
                    updated += 1
                    if last_sold_date:
                        print(f"  [OK] last_sold={last_sold_date} history={len(property_history)} chars")
                    else:
                        print(f"  [OK] history={len(property_history)} chars")
                else:
                    errors += 1
            else:
                skipped += 1
                print("  [SKIP] could not parse page")

            if i < total - 1:
                time.sleep(random.uniform(1, 2))

        browser.close()

    duration = (time.time() - start_time) / 60
    print(f"\n{'='*50}")
    print(f"Table: {table}")
    print(f"  Fetched:   {total}")
    print(f"  Updated:   {updated}")
    print(f"  Skipped:   {skipped}")
    print(f"  Errors:    {errors}")
    print(f"  Duration:  {duration:.1f} min")
    print(f"{'='*50}")

    remaining_after = count_remaining(table)
    if remaining_after == 0 and task_id:
        set_task_complete(task_id)


def main():
    parser = argparse.ArgumentParser(description="Backfill property_history from detail pages")
    parser.add_argument(
        "--table",
        choices=["real_estate", "real_estate_rent", "all"],
        default="all",
        help="Table to backfill",
    )
    parser.add_argument("--limit", type=int, help="Max records to process per table")
    parser.add_argument("--max-runtime", type=float, default=5, help="Max runtime in hours")
    parser.add_argument("--task-id", type=int, default=7, help="scraping_progress task ID for breakpoint resume")
    args = parser.parse_args()

    tables = ["real_estate", "real_estate_rent"] if args.table == "all" else [args.table]
    for t in tables:
        backfill(t, limit=args.limit, max_runtime_hours=args.max_runtime, task_id=args.task_id)
        print()


if __name__ == "__main__":
    main()
