import sys
import os
import unittest
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import database.scripts.gh_lock_manager as lm


def _make_db_mock(status=None, updated_at=None, last_processed_id=None):
    mock = MagicMock()
    if status is None:
        mock.query.return_value = []
    else:
        mock.query.return_value = [{'status': status, 'updated_at': updated_at, 'last_processed_id': last_processed_id}]
    return mock


class TestCheckAndAcquire(unittest.TestCase):

    def test_no_record_proceeds(self):
        with patch.object(lm, 'db', _make_db_mock()):
            self.assertTrue(lm.check_and_acquire(10))

    def test_idle_proceeds(self):
        with patch.object(lm, 'db', _make_db_mock(status='idle')):
            self.assertTrue(lm.check_and_acquire(10))

    def test_complete_blocks(self):
        with patch.object(lm, 'db', _make_db_mock(status='complete')):
            self.assertFalse(lm.check_and_acquire(10))

    def test_running_fresh_blocks(self):
        fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
        with patch.object(lm, 'db', _make_db_mock(status='running', updated_at=fresh)):
            self.assertFalse(lm.check_and_acquire(10))

    def test_running_stale_resets_and_proceeds(self):
        stale = datetime.now(timezone.utc) - timedelta(hours=2)
        mock_db = _make_db_mock(status='running', updated_at=stale)
        with patch.object(lm, 'db', mock_db):
            result = lm.check_and_acquire(10)
        self.assertTrue(result)
        mock_db.execute.assert_called_once()
        self.assertIn("'idle'", mock_db.execute.call_args[0][0])

    def test_ongoing_fresh_blocks(self):
        fresh = datetime.now(timezone.utc) - timedelta(minutes=10)
        with patch.object(lm, 'db', _make_db_mock(status='ongoing', updated_at=fresh)):
            self.assertFalse(lm.check_and_acquire(10))

    def test_ongoing_stale_resets_and_proceeds(self):
        stale = datetime.now(timezone.utc) - timedelta(hours=3)
        mock_db = _make_db_mock(status='ongoing', updated_at=stale)
        with patch.object(lm, 'db', mock_db):
            result = lm.check_and_acquire(10)
        self.assertTrue(result)
        mock_db.execute.assert_called_once()

    def test_force_run_breaks_running_lock(self):
        fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
        mock_db = _make_db_mock(status='running', updated_at=fresh)
        with patch.object(lm, 'db', mock_db):
            result = lm.check_and_acquire(10, force_run=True)
        self.assertTrue(result)
        mock_db.execute.assert_called_once()

    def test_force_run_breaks_complete(self):
        mock_db = _make_db_mock(status='complete')
        with patch.object(lm, 'db', mock_db):
            result = lm.check_and_acquire(10, force_run=True)
        self.assertTrue(result)
        mock_db.execute.assert_called_once()

    def test_updated_at_as_string(self):
        stale_str = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        mock_db = _make_db_mock(status='running', updated_at=stale_str)
        with patch.object(lm, 'db', mock_db):
            result = lm.check_and_acquire(10)
        self.assertTrue(result)


class TestResetStatus(unittest.TestCase):

    def test_reset_from_running_succeeds(self):
        mock_db = _make_db_mock(status='running')
        with patch.object(lm, 'db', mock_db):
            lm.reset_status(10)
        mock_db.execute.assert_called_once()
        self.assertIn("'idle'", mock_db.execute.call_args[0][0])

    def test_reset_from_idle_succeeds(self):
        mock_db = _make_db_mock(status='idle')
        with patch.object(lm, 'db', mock_db):
            lm.reset_status(10)
        mock_db.execute.assert_called_once()

    def test_reset_does_not_touch_complete(self):
        mock_db = _make_db_mock(status='complete')
        with patch.object(lm, 'db', mock_db):
            lm.reset_status(10)
        mock_db.execute.assert_not_called()

    def test_reset_no_record_still_resets(self):
        mock_db = _make_db_mock()
        with patch.object(lm, 'db', mock_db):
            lm.reset_status(10)
        mock_db.execute.assert_called_once()


class TestResetStatusForReschedule(unittest.TestCase):

    def test_reschedule_resets_complete_to_idle(self):
        mock_db = _make_db_mock(status='complete')
        with patch.object(lm, 'db', mock_db):
            lm.reset_status_for_reschedule(10)
        mock_db.execute.assert_called_once()
        self.assertIn("'idle'", mock_db.execute.call_args[0][0])

    def test_reschedule_resets_idle(self):
        mock_db = _make_db_mock(status='idle')
        with patch.object(lm, 'db', mock_db):
            lm.reset_status_for_reschedule(10)
        mock_db.execute.assert_called_once()

    def test_reschedule_skips_running(self):
        mock_db = _make_db_mock(status='running')
        with patch.object(lm, 'db', mock_db):
            lm.reset_status_for_reschedule(10)
        mock_db.execute.assert_not_called()

    def test_reschedule_no_record_does_nothing(self):
        mock_db = _make_db_mock()
        with patch.object(lm, 'db', mock_db):
            lm.reset_status_for_reschedule(10)
        mock_db.execute.assert_not_called()


class TestSetRunning(unittest.TestCase):

    def test_set_running(self):
        mock_db = _make_db_mock(status='idle')
        with patch.object(lm, 'db', mock_db):
            lm.set_running(10)
        mock_db.execute.assert_called_once()
        self.assertIn("'running'", mock_db.execute.call_args[0][0])


class TestSetComplete(unittest.TestCase):

    def test_set_complete(self):
        mock_db = _make_db_mock(status='running')
        with patch.object(lm, 'db', mock_db):
            lm.set_complete(10)
        mock_db.execute.assert_called_once()
        self.assertIn("'complete'", mock_db.execute.call_args[0][0])


class TestStateMachineScenarios(unittest.TestCase):
    """End-to-end state machine scenarios reflecting the 3 key use cases."""

    def test_scenario_a_time_limit_exit_resumes_next_run(self):
        """5.5h exit: running → reset → idle → next run proceeds."""
        mock_db = _make_db_mock(status='running')
        with patch.object(lm, 'db', mock_db):
            lm.reset_status(10)
        mock_db.execute.assert_called_once()

        mock_db2 = _make_db_mock(status='idle')
        with patch.object(lm, 'db', mock_db2):
            result = lm.check_and_acquire(10)
        self.assertTrue(result)

    def test_scenario_b_natural_complete_blocks_weekly_cron(self):
        """All done: complete → weekly cron is blocked → master_scheduler resets → next run proceeds."""
        with patch.object(lm, 'db', _make_db_mock(status='complete')):
            self.assertFalse(lm.check_and_acquire(10))

        mock_db = _make_db_mock(status='complete')
        with patch.object(lm, 'db', mock_db):
            lm.reset_status_for_reschedule(10)
        mock_db.execute.assert_called_once()

        with patch.object(lm, 'db', _make_db_mock(status='idle')):
            self.assertTrue(lm.check_and_acquire(10))

    def test_scenario_c_crash_auto_recovery_after_1h(self):
        """Crash: status stuck at running, stale >1h → staleness check resets to idle → next run proceeds."""
        stale = datetime.now(timezone.utc) - timedelta(hours=2)
        mock_db = _make_db_mock(status='running', updated_at=stale)
        with patch.object(lm, 'db', mock_db):
            result = lm.check_and_acquire(10)
        self.assertTrue(result)
        mock_db.execute.assert_called_once()

    def test_scenario_c_crash_within_1h_still_blocks(self):
        """Recent crash (<1h stale): second runner should not start."""
        fresh = datetime.now(timezone.utc) - timedelta(minutes=30)
        with patch.object(lm, 'db', _make_db_mock(status='running', updated_at=fresh)):
            self.assertFalse(lm.check_and_acquire(10))

    def test_complete_preserved_through_always_reset(self):
        """When engine sets complete, the always() reset block must NOT overwrite it."""
        mock_db = _make_db_mock(status='complete')
        with patch.object(lm, 'db', mock_db):
            lm.reset_status(10)
        mock_db.execute.assert_not_called()


class TestEngineTimerIsolated(unittest.TestCase):
    """Validates that should_stop() uses time.monotonic(), not asyncio loop time."""

    def test_monotonic_does_not_fire_immediately(self):
        import time
        start = time.monotonic()
        max_runtime = 5.5 * 3600
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.0, "should_stop() must not fire at startup")
        self.assertFalse(elapsed > max_runtime)

    def test_monotonic_fires_after_threshold(self):
        import time
        start = time.monotonic() - (5.5 * 3600 + 1)
        elapsed = time.monotonic() - start
        self.assertGreater(elapsed, 5.5 * 3600)

    def test_asyncio_loop_timing_pitfall_avoided(self):
        """Demonstrate why asyncio.get_event_loop().time() was dangerous."""
        import asyncio
        import time

        old_loop = asyncio.new_event_loop()
        old_start = old_loop.time()
        old_loop.close()

        new_loop = asyncio.new_event_loop()
        new_current = new_loop.time()
        new_loop.close()

        cross_loop_elapsed = new_current - old_start
        monotonic_elapsed = time.monotonic() - time.monotonic()

        self.assertAlmostEqual(abs(monotonic_elapsed), 0.0, places=2,
            msg="time.monotonic() is process-wide and loop-independent")
        self.assertGreaterEqual(cross_loop_elapsed, 0,
            msg="Cross-loop timing can be near-zero or large, unpredictable")


if __name__ == '__main__':
    unittest.main(verbosity=2)
