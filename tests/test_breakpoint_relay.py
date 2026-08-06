import unittest
import json
import time
from unittest.mock import MagicMock, patch
import asyncio
import sys
import os

sys.path.append(os.getcwd())

# --- CRITICAL: Mock the DB BEFORE importing anything that uses it ---
class MockDB:
    def __init__(self):
        self.data = {
            10: {"status": "idle", "last_processed_id": None,
                  "suburbs_target": None, "suburbs_completed": None,
                  "total_suburbs": 0, "completed_suburbs": 0, "remaining_count": None}
        }
    def query(self, sql, params=None):
        if "SELECT" in sql:
            task_id = params[0] if params else 10
            row = self.data.get(task_id)
            return [row] if row else []
        return []
    def execute(self, sql, params=None):
        sql_upper = sql.upper()
        params = params or []
        # Status: UPSERT params are (id, status, last_processed_id)
        if "UPSERT" in sql_upper and len(params) >= 2:
            self.data[10]["status"] = params[1]
        if "status = 'running'" in sql: self.data[10]["status"] = "running"
        if "status = 'idle'" in sql: self.data[10]["status"] = "idle"
        if "status = 'complete'" in sql: self.data[10]["status"] = "complete"
        # last_processed_id: from UPSERT 3rd param, or named update param
        if "UPSERT" in sql_upper and "last_processed_id" in sql and len(params) >= 3:
            self.data[10]["last_processed_id"] = params[2]
        elif "last_processed_id =" in sql and params:
            self.data[10]["last_processed_id"] = params[1] if len(params) > 1 else params[0]
        # suburb-progress columns
        if "suburbs_target" in sql and params:
            self.data[10]["suburbs_target"] = params[0]
        if "suburbs_completed" in sql and params:
            self.data[10]["suburbs_completed"] = params[0]
        if "total_suburbs" in sql and len(params) >= 3:
            self.data[10]["total_suburbs"] = params[2]
        if "remaining_count" in sql and params:
            self.data[10]["remaining_count"] = params[0]

# Global mock instance
the_mock_db = MockDB()

# Patch the entire module before importing
with patch('utils.database.db', the_mock_db):
    from scrapers.property_value_engine import PropertyValueEngine
    import database.scripts.gh_lock_manager as lm

class TestBreakpointRelayExpert(unittest.TestCase):
    def test_full_handoff_cycle(self):
        # --- PHASE 1: Runner A starts ---
        self.assertEqual(the_mock_db.data[10]["status"], "idle")
        
        engine_a = PropertyValueEngine(mode="discovery", region="auckland", task_id=10)
        engine_a.simulate = False 
        
        # Manually trigger set_status_by_id with the patched DB
        # Since PropertyValueEngine already imported 'db', we must ensure it uses the mock
        with patch('scrapers.property_value_engine.db', the_mock_db):
            asyncio.run(engine_a.set_status_by_id(10, "running"))
            self.assertEqual(the_mock_db.data[10]["status"], "running")

            # Simulate timeout
            checkpoint = json.dumps({"ta_idx": 0, "sub_idx": 2, "page_num": 425})
            asyncio.run(engine_a.set_status_by_id(10, "running", checkpoint))
        
        # --- PHASE 2: GitHub Action Reset ---
        with patch('database.scripts.gh_lock_manager.db', the_mock_db):
            lm.reset_status(10)
        
        self.assertEqual(the_mock_db.data[10]["status"], "idle")
        self.assertEqual(json.loads(the_mock_db.data[10]["last_processed_id"])["page_num"], 425)

        # --- PHASE 3: Runner B Resumes ---
        engine_b = PropertyValueEngine(mode="discovery", region="auckland", task_id=10)
        engine_b.simulate = False
        
        with patch('scrapers.property_value_engine.db', the_mock_db):
            state = asyncio.run(engine_b.get_state())
            self.assertEqual(state["page_num"], 425)
            
            # Simulate completion
            asyncio.run(engine_b.set_status_by_id(10, "complete", json.dumps({"ta_idx": 0, "sub_idx": 0, "page_num": 1})))
        
        # --- PHASE 4: Final Verification ---
        with patch('database.scripts.gh_lock_manager.db', the_mock_db):
            lm.reset_status(10)
            
        self.assertEqual(the_mock_db.data[10]["status"], "complete")
        print("\n[SUCCESS] Verified full Relay cycle: Runner A (5.5h) -> Runner B (Resume) -> Complete")

if __name__ == "__main__":
    unittest.main()
