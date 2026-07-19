"""
Unified backfill for real_estate and real_estate_rent.

Extracts from realestate.co.nz detail pages:
  - car_spaces        → from features-icons (Garage + Other park)
  - property_history  → from sale-history rows (JSON array)
  - last_sold_date    → most recent "Sold" event date

All three are extracted in a single page visit and updated together.

Features:
  - Breakpoint resume via scraping_progress (gh_lock_manager compatible)
  - Auto-complete when no records remain
  - Idempotent: skips records already backfilled (property_history IS NULL OR car_spaces IS NULL)

Usage:
    python scripts/backfill_realestate.py [--table real_estate] [--limit 100] [--max-runtime 5] [--task-id 7]
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
    """Get records missing car_spaces or property_history with a valid property_url."""
    sql = f"SELECT id, property_url, address, suburb, city FROM {table} WHERE (car_spaces IS NULL OR property_history IS NULL) AND property_url IS NOT NULL ORDER BY id"
    params = []
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    return db.query(sql, params) or []


def count_remaining(table):
    """Count how many records still need backfill."""
    rows = db.query(
        f"SELECT COUNT(*) AS cnt FROM {table} WHERE (car_spaces IS NULL OR property_history IS NULL) AND property_url IS NOT NULL"
    )
    return rows[0]['cnt'] if rows else 0


def extract_car_spaces(page):
    """Extract car_spaces count from features-icons section."""
    try:
        page.wait_for_selector('div[data-test="features-icons"]', timeout=15000)
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
                    if (!isNaN(val)) { total += val; found = true; }
                }
            }
            return found ? total : null;
        }
    """)
    return result


def extract_property_history(page):
    """Parse property history from sale-history rows.

    Returns (property_history_json, last_sold_date_str_or_None).
    """
    try:
        page.wait_for_selector('div[data-test="sale-history-row"]', timeout=10000)
    except Exception:
        pass

    rows = page.query_selector_all('div[data-test="sale-history-row"]')
    if not rows:
        return None, None

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

        events.append({"date": date_text, "type": type_text, "value": value_text, "metadata": meta_text})

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


def update_record(table, record_id, car_spaces, property_history, last_sold_date):
    """Update car_spaces, property_history and last_sold_date for a given record."""
    try:
        db.execute(
            f"UPDATE {table} SET car_spaces = COALESCE(%s, car_spaces), property_history = COALESCE(%s, property_history), last_sold_date = COALESCE(%s, last_sold_date) WHERE id = %s",
            (car_spaces, property_history, last_sold_date, record_id),
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
    logger.info(f"Backfilling {table}: {remaining} records need data")

    if remaining == 0:
        print(f"[OK] {table}: No records need backfill")
        if task_id:
            set_task_complete(task_id)
        return

    records = get_records_to_backfill(table, limit)
    total = len(records)
    logger.info(f"Fetched {total} records for processing")

    start_time = time.time()
    max_seconds = max_runtime_hours * 3600
    updated_car = 0
    updated_hist = 0
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

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(1.5, 3))
            except Exception as e:
                logger.warning(f"  Navigation failed: {e}")
                errors += 1
                if i < total - 1:
                    time.sleep(random.uniform(1, 2))
                continue

            car_spaces = extract_car_spaces(page)
            property_history, last_sold_date = extract_property_history(page)

            parts = []
            if car_spaces is not None:
                parts.append(f"car={car_spaces}")
            if property_history:
                parts.append(f"history={len(property_history)} chars")
                if last_sold_date:
                    parts.append(f"sold={last_sold_date}")

            if parts or (car_spaces is None and property_history is None):
                if update_record(table, rid, car_spaces, property_history, last_sold_date):
                    if car_spaces is not None:
                        updated_car += 1
                    if property_history:
                        updated_hist += 1
                    print(f"  [OK] {' | '.join(parts) if parts else 'no data found (marked done)'}")
                else:
                    errors += 1
            else:
                # car_spaces is None AND no property_history found on page
                if not property_history and car_spaces is None:
                    errors += 1
                    print("  [ERR] could not parse page")
                else:
                    errors += 1

            if i < total - 1:
                time.sleep(random.uniform(1, 2))

        browser.close()

    duration = (time.time() - start_time) / 60
    print(f"\n{'='*50}")
    print(f"Table: {table}")
    print(f"  Fetched:     {total}")
    print(f"  Car spaces:  {updated_car}")
    print(f"  History:     {updated_hist}")
    print(f"  Errors:      {errors}")
    print(f"  Duration:    {duration:.1f} min")
    print(f"{'='*50}")

    remaining_after = count_remaining(table)
    if remaining_after == 0 and task_id:
        set_task_complete(task_id)


def main():
    parser = argparse.ArgumentParser(description="Backfill car_spaces, property_history, last_sold_date from detail pages")
    parser.add_argument(
        "--table",
        choices=["real_estate", "real_estate_rent", "all"],
        default="all",
        help="Table to backfill",
    )
    parser.add_argument("--limit", type=str, default="", help="Max records to process (number, or 'all'/'0' for unlimited)")
    parser.add_argument("--max-runtime", type=float, default=5, help="Max runtime in hours")
    parser.add_argument("--task-id", type=int, default=7, help="scraping_progress task ID for breakpoint resume")
    args = parser.parse_args()

    limit_val = None
    if args.limit and args.limit not in ("all", "0", ""):
        limit_val = int(args.limit)

    tables = ["real_estate", "real_estate_rent"] if args.table == "all" else [args.table]
    for t in tables:
        backfill(t, limit=limit_val, max_runtime_hours=args.max_runtime, task_id=args.task_id)
        print()


if __name__ == "__main__":
    main()
