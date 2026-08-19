import unittest
import sys
import os
from unittest.mock import patch

sys.path.append(os.getcwd())


class MockDB:
    def __init__(self, row):
        self.row = row
    def query(self, sql, params=None):
        return [self.row] if self.row else []


class TestResumeState(unittest.TestCase):
    def _check(self, row):
        import database.scripts.check_resume_state as crs
        with patch('database.scripts.check_resume_state.db', MockDB(row)):
            return crs.check(10)

    def test_complete_status(self):
        self.assertEqual(self._check({"status": "complete", "remaining_count": None,
                                      "total_suburbs": 10, "completed_suburbs": 10,
                                      "last_processed_id": None}), "COMPLETE")

    def test_complete_but_backfill_pending(self):
        self.assertEqual(self._check({"status": "complete", "remaining_count": 5,
                                      "total_suburbs": 10, "completed_suburbs": 10,
                                      "last_processed_id": None}), "HAS_PROGRESS")

    def test_remaining_count_positive(self):
        self.assertEqual(self._check({"status": "running", "remaining_count": 42,
                                      "total_suburbs": 0, "completed_suburbs": 0,
                                      "last_processed_id": None}), "HAS_PROGRESS")

    def test_discovery_incomplete(self):
        self.assertEqual(self._check({"status": "running", "remaining_count": 0,
                                      "total_suburbs": 10, "completed_suburbs": 6,
                                      "last_processed_id": None}), "HAS_PROGRESS")

    def test_page_progress(self):
        self.assertEqual(self._check({"status": "running", "remaining_count": None,
                                      "total_suburbs": 0, "completed_suburbs": 0,
                                      "last_processed_id": '{"ta_idx": 0, "sub_idx": 2, "page_num": 100}'}),
                         "HAS_PROGRESS")

    def test_no_progress(self):
        self.assertEqual(self._check({"status": "running", "remaining_count": None,
                                      "total_suburbs": 0, "completed_suburbs": 0,
                                      "last_processed_id": '{"ta_idx": 0, "sub_idx": 0, "page_num": 1}'}),
                         "NO_PROGRESS")

    def test_no_record(self):
        self.assertEqual(self._check(None), "NO_PROGRESS")


if __name__ == "__main__":
    unittest.main()
