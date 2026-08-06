"""
Unified breakpoint-resume decision helper for GitHub Actions workflows.

Prints one of:
  COMPLETE      - task is finished, no more runs needed
  HAS_PROGRESS  - saved progress exists, workflow should re-trigger itself
  NO_PROGRESS   - no resumable progress, do not auto-re-trigger

This logic is shared by all property_value_engine workflows so the resume
behaviour stays consistent and testable.
"""
import sys
import os
import json
import argparse

sys.path.append(os.getcwd())
from utils.database import db


def check(task_id):
    rows = db.query(
        "SELECT status, last_processed_id, total_suburbs, completed_suburbs, remaining_count "
        "FROM scraping_progress WHERE id = %s",
        (task_id,)
    )
    if not rows:
        return "NO_PROGRESS"

    r = rows[0]
    status = r.get('status')

    if status == 'complete':
        return "COMPLETE"

    remaining = r.get('remaining_count')
    if remaining is not None and remaining > 0:
        return "HAS_PROGRESS"

    total = int(r.get('total_suburbs') or 0)
    completed = int(r.get('completed_suburbs') or 0)
    if total > 0 and completed < total:
        return "HAS_PROGRESS"

    state = r.get('last_processed_id')
    if state:
        try:
            s = json.loads(state)
            if s.get('ta_idx', 0) > 0 or s.get('sub_idx', 0) > 0 or s.get('page_num', 1) > 1:
                return "HAS_PROGRESS"
        except Exception:
            pass

    return "NO_PROGRESS"


def main():
    parser = argparse.ArgumentParser(description="Determine if a scraping task has resumable progress.")
    parser.add_argument("--task-id", type=int, required=True)
    args = parser.parse_args()

    result = check(args.task_id)
    print(result)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"resume_state={result}\n")


if __name__ == "__main__":
    main()
