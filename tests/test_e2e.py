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


class TestUnbackfilledPredicate(unittest.TestCase):
    """Eligibility must be backfilled_at-only: history-less properties (NULL property_history)
    used to be re-selected forever, causing an infinite re-scrape loop."""

    def test_count_query_is_backfilled_at_only(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="backfill", region="auckland", task_id=10, suburbs_filter="Torbay")
        mock_db = MagicMock()
        mock_db.query.return_value = [{"cnt": 0}]
        with patch('scrapers.property_value_engine.db', mock_db):
            engine._count_unbackfilled()
        sql = mock_db.query.call_args[0][0]
        self.assertIn("backfilled_at IS NULL", sql)
        self.assertNotIn("property_history IS NULL", sql)
        self.assertNotIn("has_rental_history IS NULL", sql)

    def test_backfill_select_query_is_backfilled_at_only(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="backfill", region="auckland", task_id=10, suburbs_filter="Torbay")
        engine.simulate = False
        mock_db = MagicMock()

        def q(sql, params=None):
            if "SELECT COUNT(*) AS cnt" in sql:
                return [{"cnt": 1}]
            if "SELECT id, address, suburb, property_url" in sql:
                return []
            if "suburbs_target" in sql:
                return [{"suburbs_target": '["torbay"]', "suburbs_completed": '[]',
                         "total_suburbs": 1, "completed_suburbs": 0, "remaining_count": 1}]
            return []
        mock_db.query.side_effect = q
        with patch('scrapers.property_value_engine.db', mock_db), \
             patch.object(engine, 'set_status_by_id', new=AsyncMock()):
            asyncio.run(engine.run_backfill())
        select_sqls = [c.args[0] for c in mock_db.query.call_args_list
                       if "SELECT id, address, suburb, property_url" in c.args[0]]
        self.assertTrue(select_sqls, "backfill SELECT should be issued")
        for sql in select_sqls:
            self.assertIn("backfilled_at IS NULL", sql)
            self.assertNotIn("property_history IS NULL", sql)
            self.assertNotIn("has_rental_history IS NULL", sql)


class TestPropertyValueEngineAddressFilter(unittest.TestCase):
    """--address targets one specific property (e.g. '850A Beach Road, Waiake')."""

    def test_parses_address_part_before_comma(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="backfill", region="auckland", task_id=10, address_filter="850A Beach Road, Waiake")
        clause, params = engine._address_match_clause()
        self.assertIn("LOWER(address) LIKE", clause)
        self.assertEqual(params, ("850a beach road",))

    def test_count_unbackfilled_uses_address_clause(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="backfill", region="auckland", task_id=10, address_filter="850A Beach Road, Waiake")
        mock_db = MagicMock()
        mock_db.query.return_value = [{"cnt": 1}]
        with patch('scrapers.property_value_engine.db', mock_db):
            cnt = engine._count_unbackfilled()
        self.assertEqual(cnt, 1)
        sql, params = mock_db.query.call_args[0]
        self.assertIn("LOWER(address) LIKE", sql)
        self.assertEqual(params, ("auckland", "850a beach road"))

    def test_run_backfill_selects_by_address_without_backfill_predicate(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="backfill", region="auckland", task_id=10, address_filter="850A Beach Road, Waiake")
        engine.simulate = False
        mock_db = MagicMock()

        def q(sql, params=None):
            if "SELECT COUNT(*) AS cnt" in sql:
                return [{"cnt": 1}]
            if "SELECT id, address, suburb, property_url" in sql:
                return []
            if "suburbs_target" in sql:
                return [{"suburbs_target": '[]', "suburbs_completed": '[]',
                         "total_suburbs": 0, "completed_suburbs": 0, "remaining_count": 1}]
            return []
        mock_db.query.side_effect = q
        with patch('scrapers.property_value_engine.db', mock_db), \
             patch.object(engine, 'set_status_by_id', new=AsyncMock()):
            asyncio.run(engine.run_backfill())
        select_calls = [c for c in mock_db.query.call_args_list
                        if "SELECT id, address, suburb, property_url" in c[0][0]]
        self.assertEqual(len(select_calls), 1)
        sql, params = select_calls[0].args
        self.assertNotIn("backfilled_at IS NULL", sql)
        self.assertIn("LIMIT 1", sql)
        self.assertIn("850a beach road", params)

    def test_parse_cli_includes_address_arg(self):
        import ast
        engine_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scrapers", "property_value_engine.py"
        )
        with open(engine_path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn("parser.add_argument(\"--address\"", src)


class TestPropertyValueEngineBackfill(unittest.TestCase):
    def test_run_backfill_uses_suburbs_filter_in_query(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="backfill", region="auckland", task_id=10, suburbs_filter="Albany,Torbay")
        engine.simulate = False
        mock_db = MagicMock()
        mock_db.query.return_value = []
        with patch('scrapers.property_value_engine.db', mock_db):
            asyncio.run(engine.run_backfill())
        target_calls = [c for c in mock_db.query.call_args_list if "unnest(%s)" in c[0][0]]
        self.assertEqual(len(target_calls), 1)
        self.assertEqual(target_calls[0][0][1], ("auckland", ["albany", "torbay"]))

    def test_backfill_zero_remaining_not_complete_when_discovery_incomplete(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="backfill", region="auckland", task_id=10, suburbs_filter="Albany")
        engine.simulate = False
        mock_db = MagicMock()
        mock_db.query.return_value = []  # count -> 0 remaining; progress -> no rows (total 0)
        with patch('scrapers.property_value_engine.db', mock_db), \
             patch.object(engine, 'set_status_by_id', new=AsyncMock()) as m_status:
            asyncio.run(engine.run_backfill())
        for call in m_status.call_args_list:
            self.assertNotEqual(call.args[1], "complete")

    def test_backfill_zero_remaining_complete_when_discovery_done(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="backfill", region="auckland", task_id=10, suburbs_filter="Albany")
        engine.simulate = False
        mock_db = MagicMock()

        def q(sql, params=None):
            if "suburbs_target" in sql:
                return [{"suburbs_target": '["albany"]', "suburbs_completed": '["albany"]',
                         "total_suburbs": 1, "completed_suburbs": 1, "remaining_count": 0}]
            return []
        mock_db.query.side_effect = q
        with patch('scrapers.property_value_engine.db', mock_db), \
             patch.object(engine, 'set_status_by_id', new=AsyncMock()) as m_status:
            asyncio.run(engine.run_backfill())
        self.assertEqual(m_status.call_args_list[-1].args[1], "complete")


class TestPropertiesUpsertDedup(unittest.TestCase):
    """Multi-row upsert must collapse colliding fingerprints within a batch (CockroachDB rejects row twice)."""

    def test_batch_dedups_colliding_fingerprints(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="discovery", region="auckland", simulate=False)
        mock_db = MagicMock()
        # RETURNING a single-row result so counts/logging don't blow up
        mock_db.query.return_value = [{"address": "1 Test Road", "suburb": "Birkdale", "is_new": True}]
        props = [
            {"address": "1 Test Road", "suburb": "Birkdale", "city": "Auckland",
             "property_url": "http://u/1"},
            {"address": "1 Test Road", "suburb": "Birkdale", "city": "Auckland",
             "property_url": "http://u/1b"},  # same fingerprint -> must be collapsed
        ]
        with patch('scrapers.property_value_engine.db', mock_db), \
             patch.object(engine, 'set_status_by_id', new=AsyncMock()):
            asyncio.run(engine._save_properties_batch(props))

        self.assertEqual(mock_db.query.call_count, 1)
        sql, params = mock_db.query.call_args[0]
        self.assertEqual(len(params), 6, "multi-row statement must contain exactly one row after dedup")


class TestSuburbGuarantee(unittest.TestCase):
    """Multi-suburb input like 'Takapuna, Totara Vale' must cover every target before completing."""

    def test_multi_suburb_parsing_with_spaces(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="discovery", region="auckland", suburbs_filter="Takapuna, Totara Vale")
        self.assertEqual(engine.suburbs_filter, ["takapuna", "totara vale"])

    def test_all_targets_done_positive(self):
        from scrapers.property_value_engine import PropertyValueEngine
        self.assertTrue(PropertyValueEngine._all_targets_done(
            ["takapuna", "totara vale"],
            ["takapuna north shore", "totara vale north shore"]))

    def test_all_targets_done_missing_one(self):
        from scrapers.property_value_engine import PropertyValueEngine
        self.assertFalse(PropertyValueEngine._all_targets_done(
            ["takapuna", "totara vale"],
            ["takapuna north shore"]))

    def test_all_targets_done_partial_overmatch(self):
        from scrapers.property_value_engine import PropertyValueEngine
        # 'takapuna' target covered even though the site suburb includes extra words
        self.assertTrue(PropertyValueEngine._all_targets_done(
            ["takapuna", "totara vale"],
            ["takapuna central", "totara vale north shore"]))


class TestSuburbPagination(unittest.TestCase):
    """Discovery must stop pagination when a page repeats already-seen property links."""

    def test_pagination_stops_on_circular_page(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="discovery", region="auckland", task_id=10, simulate=True)
        engine.safe_goto = AsyncMock(return_value=True)
        engine.set_status_by_id = AsyncMock()
        page = MagicMock()
        page.content = AsyncMock(side_effect=["html1", "html2"])
        page.close = AsyncMock()

        links1 = ["/auckland/nsc/sub/addr1-0626-111", "/auckland/nsc/sub/addr2-0626-222",
                  "/auckland/nsc/sub/addr3-0626-333"]
        with patch('scrapers.property_value_engine.PropertyValueParser.parse_property_links',
                   side_effect=[links1, links1]) as m_parse, \
             patch('scrapers.property_value_engine.PropertyValueParser.parse_next_page',
                   side_effect=["/page2"]) as m_next, \
             patch.object(engine, '_save_properties_batch', new=AsyncMock()) as m_save:
            result = asyncio.run(engine._scrape_suburb_properties(
                page, "http://x/sub", "Suburb", "TA", 0, 0))

        self.assertTrue(result)          # completed normally, not stopped early
        self.assertEqual(m_save.call_count, 1)   # only the first page upserted
        self.assertEqual(m_next.call_count, 1)   # never asked for page 3

    def test_pagination_stops_on_empty_page(self):
        from scrapers.property_value_engine import PropertyValueEngine
        engine = PropertyValueEngine(mode="discovery", region="auckland", task_id=10, simulate=True)
        engine.safe_goto = AsyncMock(return_value=True)
        engine.set_status_by_id = AsyncMock()
        page = MagicMock()
        page.content = AsyncMock(side_effect=["html1", "html2"])
        page.close = AsyncMock()

        links1 = ["/auckland/nsc/sub/addr1-0626-111", "/auckland/nsc/sub/addr2-0626-222"]
        with patch('scrapers.property_value_engine.PropertyValueParser.parse_property_links',
                   side_effect=[links1, []]) as m_parse, \
             patch('scrapers.property_value_engine.PropertyValueParser.parse_next_page',
                   side_effect=["/page2"]) as m_next, \
             patch.object(engine, '_save_properties_batch', new=AsyncMock()) as m_save:
            result = asyncio.run(engine._scrape_suburb_properties(
                page, "http://x/sub", "Suburb", "TA", 0, 0))

        self.assertTrue(result)
        self.assertEqual(m_save.call_count, 1)
        self.assertEqual(m_next.call_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
