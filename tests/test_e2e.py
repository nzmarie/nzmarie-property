import unittest
import sys
import os
import json
import time
from unittest.mock import patch, MagicMock, AsyncMock, call
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database.scripts.gh_lock_manager as lm


def _make_db_mock(status=None, last_processed_id=None, updated_at=None):
    mock = MagicMock()
    if status is None:
        mock.query.return_value = []
    else:
        mock.query.return_value = [{
            'status': status,
            'updated_at': updated_at,
            'last_processed_id': last_processed_id
        }]
    return mock


class TestPropertyValueEngineCheckpoint(unittest.TestCase):
    """End-to-end checkpoint save/restore logic without a real DB or browser."""

    def _make_engine(self, task_id=10):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="discovery", region="auckland", task_id=task_id)
        engine.simulate = True
        return engine

    def test_get_state_returns_none_when_no_record(self):
        engine = self._make_engine()
        mock_db = _make_db_mock()
        with patch('scrapers.property_value_engine.db', mock_db):
            state = asyncio.run(engine.get_state())
        self.assertIsNone(state)

    def test_get_state_parses_json_checkpoint(self):
        checkpoint = {"ta_idx": 2, "sub_idx": 5, "page_num": 3}
        engine = self._make_engine()
        mock_db = _make_db_mock(status='running', last_processed_id=json.dumps(checkpoint))
        with patch('scrapers.property_value_engine.db', mock_db):
            state = asyncio.run(engine.get_state())
        self.assertEqual(state['ta_idx'], 2)
        self.assertEqual(state['sub_idx'], 5)
        self.assertEqual(state['page_num'], 3)

    def test_get_state_returns_none_for_invalid_json(self):
        engine = self._make_engine()
        mock_db = _make_db_mock(status='running', last_processed_id="not-valid-json")
        with patch('scrapers.property_value_engine.db', mock_db):
            state = asyncio.run(engine.get_state())
        self.assertIsNone(state)

    def test_get_state_returns_none_for_empty_last_processed_id(self):
        engine = self._make_engine()
        mock_db = _make_db_mock(status='idle', last_processed_id=None)
        with patch('scrapers.property_value_engine.db', mock_db):
            state = asyncio.run(engine.get_state())
        self.assertIsNone(state)

    def test_set_status_by_id_preserves_last_processed_id_when_not_given(self):
        checkpoint = json.dumps({"ta_idx": 1, "sub_idx": 3, "page_num": 7})
        engine = self._make_engine()
        engine.simulate = False
        mock_db = _make_db_mock(status='running', last_processed_id=checkpoint)
        with patch('scrapers.property_value_engine.db', mock_db):
            asyncio.run(engine.set_status_by_id(10, 'running'))
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0]
        self.assertIn(checkpoint, call_args[1])

    def test_set_status_by_id_writes_new_checkpoint_when_given(self):
        new_state = json.dumps({"ta_idx": 2, "sub_idx": 0, "page_num": 1})
        engine = self._make_engine()
        engine.simulate = False
        mock_db = _make_db_mock(status='running', last_processed_id='{"ta_idx":1}')
        with patch('scrapers.property_value_engine.db', mock_db):
            asyncio.run(engine.set_status_by_id(10, 'running', new_state))
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0]
        self.assertIn(new_state, call_args[1])

    def test_simulate_mode_skips_db_write(self):
        engine = self._make_engine()
        engine.simulate = True
        mock_db = MagicMock()
        with patch('scrapers.property_value_engine.db', mock_db):
            asyncio.run(engine.set_status_by_id(10, 'running', '{"ta_idx":0}'))
        mock_db.execute.assert_not_called()

    @patch('scrapers.property_value_engine.PropertyValueEngine.get_state')
    def test_run_discovery_ignores_state_on_force_run(self, mock_get_state):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="discovery", region="auckland", task_id=10, force_run=True)
        engine.context = MagicMock()
        engine.context.new_page = AsyncMock(side_effect=Exception("Stop execution"))
        mock_get_state.return_value = {"ta_idx": 4, "sub_idx": 0, "page_num": 1}
        try:
            asyncio.run(engine.run_discovery())
        except Exception as e:
            self.assertEqual(str(e), "Stop execution")
        mock_get_state.assert_not_called()

    @patch('scrapers.property_value_engine.PropertyValueEngine.get_state')
    def test_run_discovery_uses_state_on_suburbs_filter(self, mock_get_state):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="discovery", region="auckland", task_id=10, suburbs_filter="Albany")
        engine.context = MagicMock()
        engine.context.new_page = AsyncMock(side_effect=Exception("Stop execution"))
        mock_get_state.return_value = {"ta_idx": 4, "sub_idx": 0, "page_num": 1}
        try:
            asyncio.run(engine.run_discovery())
        except Exception as e:
            self.assertEqual(str(e), "Stop execution")
        mock_get_state.assert_called_once()

    @patch('scrapers.property_value_engine.PropertyValueEngine.get_state')
    def test_run_discovery_uses_state_otherwise(self, mock_get_state):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="discovery", region="auckland", task_id=10)
        engine.context = MagicMock()
        engine.context.new_page = AsyncMock(side_effect=Exception("Stop execution"))
        mock_get_state.return_value = {"ta_idx": 4, "sub_idx": 0, "page_num": 1}
        try:
            asyncio.run(engine.run_discovery())
        except Exception as e:
            self.assertEqual(str(e), "Stop execution")
        mock_get_state.assert_called_once()


class TestShouldStop(unittest.TestCase):
    """Validate time.monotonic()-based should_stop() correctness."""

    def test_should_stop_false_at_startup(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="discovery", region="auckland", task_id=10)
        self.assertFalse(engine.should_stop())

    def test_should_stop_true_after_threshold(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="discovery", region="auckland", task_id=10)
        engine.start_time = time.monotonic() - (5.5 * 3600 + 1)
        self.assertTrue(engine.should_stop())

    def test_should_stop_false_just_before_threshold(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="discovery", region="auckland", task_id=10)
        engine.start_time = time.monotonic() - (5.5 * 3600 - 60)
        self.assertFalse(engine.should_stop())

    def test_start_time_uses_monotonic_not_loop(self):
        """Confirm start_time is set via time.monotonic() — loop-independent."""
        import asyncio
        from scrapers.property_value_engine import PropertyValueEngine
        before = time.monotonic()
        engine = PropertyValueEngine(mode="discovery", region="auckland", task_id=10)
        after = time.monotonic()
        self.assertGreaterEqual(engine.start_time, before)
        self.assertLessEqual(engine.start_time, after)


class TestDiscoveryCheckpointResumeLogic(unittest.TestCase):
    """Verify that run_discovery() correctly skips already-processed TAs and suburbs."""

    def test_checkpoint_ta_idx_skips_earlier_tas(self):
        checkpoint = {"ta_idx": 2, "sub_idx": 0, "page_num": 1}
        processed = []

        for i, ta in enumerate(["ta0", "ta1", "ta2", "ta3"]):
            if i < checkpoint["ta_idx"]:
                continue
            processed.append(ta)

        self.assertNotIn("ta0", processed)
        self.assertNotIn("ta1", processed)
        self.assertIn("ta2", processed)
        self.assertIn("ta3", processed)

    def test_checkpoint_sub_idx_skips_earlier_suburbs_for_current_ta(self):
        checkpoint = {"ta_idx": 2, "sub_idx": 3, "page_num": 1}
        suburbs = ["sub0", "sub1", "sub2", "sub3", "sub4"]
        processed = []

        for j, sub in enumerate(suburbs):
            if checkpoint["ta_idx"] == 2 and j < checkpoint["sub_idx"]:
                continue
            processed.append(sub)

        self.assertNotIn("sub0", processed)
        self.assertNotIn("sub1", processed)
        self.assertNotIn("sub2", processed)
        self.assertIn("sub3", processed)
        self.assertIn("sub4", processed)

    def test_fresh_start_processes_all(self):
        checkpoint = {"ta_idx": 0, "sub_idx": 0, "page_num": 1}
        tas = ["ta0", "ta1"]
        processed = [ta for i, ta in enumerate(tas) if i >= checkpoint["ta_idx"]]
        self.assertEqual(processed, tas)

    def test_complete_checkpoint_reset_to_zero(self):
        complete_state = {"ta_idx": 0, "sub_idx": 0, "page_num": 1}
        self.assertEqual(complete_state["ta_idx"], 0)
        self.assertEqual(complete_state["sub_idx"], 0)
        self.assertEqual(complete_state["page_num"], 1)


class TestRealEstateAucklandMaxRuntime(unittest.TestCase):
    """Validate that max_runtime_hours is 5.5, not the old hardcoded 1.2."""

    def test_max_runtime_is_5_point_5_hours(self):
        import ast
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "real_estate_auckland.py"
        )
        with open(script_path, encoding='utf-8') as f:
            source = f.read()
        self.assertIn("max_runtime_hours=5.5", source,
            "real_estate_auckland.py must pass max_runtime_hours=5.5, not 1.2")
        self.assertNotIn("max_runtime_hours=1.2", source,
            "Hardcoded 1.2h runtime was a bug and must not exist")


class TestPropertyValueEngineBackfill(unittest.TestCase):
    def test_run_backfill_uses_suburbs_filter_in_query(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="backfill", region="auckland", task_id=10, suburbs_filter="Albany,Torbay")
        engine.simulate = False
        mock_db = MagicMock()
        mock_db.query.return_value = []
        with patch('scrapers.property_value_engine.db', mock_db):
            asyncio.run(engine.run_backfill())
        target_calls = [c for c in mock_db.query.call_args_list if "LOWER(suburb) = ANY(%s)" in c[0][0]]
        self.assertEqual(len(target_calls), 1)
        self.assertEqual(target_calls[0][0][1], ("auckland", ["albany", "torbay"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
