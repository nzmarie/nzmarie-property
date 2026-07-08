import os
import sys
import argparse
from datetime import datetime, timezone, timedelta
from dateutil import parser

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils.database import db

def check_and_acquire(task_id, force_run=False):
    print(f"Checking lock for Task ID: {task_id}, Force Run: {force_run}")
    
    rows = db.query("SELECT status, updated_at FROM scraping_progress WHERE id = %s", (task_id,))
    if not rows:
        print(f"No record found for task {task_id}. Proceeding...")
        return True
    
    record = rows[0]
    status = record.get('status')
    updated_at = record.get('updated_at')
    
    print(f"Current status: {status}, Updated at: {updated_at}")
    
    if force_run:
        print(f"Force run enabled. Breaking lock for task {task_id} (preserving progress)...")
        # Just set to idle, don't reset last_processed_id unless we want to start over
        db.execute("UPDATE scraping_progress SET status = 'idle', updated_at = NOW() WHERE id = %s", (task_id,))
        return True
    
    if status in ('running', 'ongoing') and updated_at:
        if isinstance(updated_at, str):
            last_update = parser.parse(updated_at)
        else:
            last_update = updated_at

        if last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) - last_update > timedelta(hours=1):
            print(f"Task {task_id} has a stale lock (>1h). Resetting to idle...")
            db.execute("UPDATE scraping_progress SET status = 'idle', updated_at = NOW() WHERE id = %s", (task_id,))
            return True
        else:
            print(f"Task {task_id} is currently {status} (updated {last_update}). Skipping new run.")
            return False

    if status == 'complete':
        print(f"Task {task_id} is complete. Skipping — reset via master_scheduler or --force.")
        return False

    return True

def reset_status(task_id):
    print(f"Resetting task {task_id} status to idle (if not complete)...")
    try:
        rows = db.query("SELECT status FROM scraping_progress WHERE id = %s", (task_id,))
        if rows and rows[0].get('status') == 'complete':
            print(f"Task {task_id} is complete. Preserving state — not resetting.")
            return
        db.execute(
            "INSERT INTO scraping_progress (id, status, updated_at) VALUES (%s, 'idle', NOW()) "
            "ON CONFLICT (id) DO UPDATE SET status = 'idle', updated_at = NOW()", 
            (task_id,)
        )
        print("Status reset to idle successfully.")
    except Exception as e:
        print(f"Failed to reset status: {e}")

def set_running(task_id):
    print(f"Setting task {task_id} status to running...")
    try:
        db.execute(
            "INSERT INTO scraping_progress (id, status, updated_at) VALUES (%s, 'running', NOW()) "
            "ON CONFLICT (id) DO UPDATE SET status = 'running', updated_at = NOW()", 
            (task_id,)
        )
        print("Status set to running successfully.")
    except Exception as e:
        print(f"Failed to set status to running: {e}")

def set_complete(task_id):
    print(f"Setting task {task_id} status to complete...")
    try:
        db.execute(
            "INSERT INTO scraping_progress (id, status, updated_at) VALUES (%s, 'complete', NOW()) "
            "ON CONFLICT (id) DO UPDATE SET status = 'complete', updated_at = NOW()", 
            (task_id,)
        )
        print("Status set to complete successfully.")
    except Exception as e:
        print(f"Failed to set status to complete: {e}")

def reset_status_for_reschedule(task_id):
    print(f"Resetting task {task_id} from complete/idle to idle for re-schedule...")
    try:
        rows = db.query("SELECT status FROM scraping_progress WHERE id = %s", (task_id,))
        if not rows:
            print(f"No record found for task {task_id}. Nothing to reset.")
            return
        status = rows[0].get('status')
        if status == 'running':
            print(f"Task {task_id} is currently running. Skipping reset to avoid data loss.")
            return
        db.execute(
            "INSERT INTO scraping_progress (id, status, updated_at) VALUES (%s, 'idle', NOW()) "
            "ON CONFLICT (id) DO UPDATE SET status = 'idle', updated_at = NOW()",
            (task_id,)
        )
        print(f"Task {task_id} reset from '{status}' to idle successfully.")
    except Exception as e:
        print(f"Failed to reset status: {e}")

def reset_full_progress(task_id):
    print(f"Full progress reset for task {task_id}: status=idle, last_processed_id=NULL (will re-scrape from page 0)...")
    try:
        rows = db.query("SELECT status FROM scraping_progress WHERE id = %s", (task_id,))
        if rows and rows[0].get('status') == 'running':
            print(f"Task {task_id} is currently running. Aborting full reset to avoid data loss.")
            return
        db.execute(
            "INSERT INTO scraping_progress (id, status, last_processed_id, updated_at) VALUES (%s, 'idle', NULL, NOW()) "
            "ON CONFLICT (id) DO UPDATE SET status = 'idle', last_processed_id = NULL, updated_at = NOW()",
            (task_id,)
        )
        print(f"Task {task_id} fully reset. Next run will start from page 0.")
    except Exception as e:
        print(f"Failed to reset full progress: {e}")

def main():
    arg_parser = argparse.ArgumentParser(description='GitHub Actions Lock Manager for CockroachDB')
    arg_parser.add_argument('--action', choices=['check', 'reset', 'reschedule', 'running', 'complete', 'reset-progress'], required=True)
    arg_parser.add_argument('--task-id', type=int, required=True)
    arg_parser.add_argument('--force', action='store_true')

    args = arg_parser.parse_args()

    if args.action == 'check':
        can_run = check_and_acquire(args.task_id, args.force)

        output_val = 'true' if can_run else 'false'
        github_output = os.environ.get('GITHUB_OUTPUT')
        if github_output:
            with open(github_output, 'a') as f:
                f.write(f"should_run={output_val}\n")
        else:
            print(f"::set-output name=should_run::{output_val}")
    elif args.action == 'reset':
        reset_status(args.task_id)
    elif args.action == 'reschedule':
        reset_status_for_reschedule(args.task_id)
    elif args.action == 'running':
        set_running(args.task_id)
    elif args.action == 'complete':
        set_complete(args.task_id)
    elif args.action == 'reset-progress':
        reset_full_progress(args.task_id)

if __name__ == "__main__":
    main()
