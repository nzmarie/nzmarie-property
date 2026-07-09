import unittest
import yaml
import os

class TestWorkflowFiles(unittest.TestCase):
    def setUp(self):
        self.workflows_dir = ".github/workflows"

    def test_property_scraper_auckland(self):
        path = os.path.join(self.workflows_dir, "property_scraper_auckland.yml")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        self.assertEqual("property-engine-auckland", content["jobs"]["scrape"]["concurrency"]["group"])

        steps = content["jobs"]["scrape"]["steps"]
        task_id_step = next(s for s in steps if s.get("id") == "task_id")
        self.assertIn("TASK_ID=10", task_id_step["run"])

        run_step = next(s for s in steps if s.get("run") and "property_value_engine.py" in s.get("run", ""))
        self.assertIn("--region", run_step["run"])

    def test_property_scraper_auckland_suburbs(self):
        path = os.path.join(self.workflows_dir, "property_scraper_auckland_suburbs.yml")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        self.assertEqual("property-engine-auckland-suburbs", content["jobs"]["scrape"]["concurrency"]["group"])

        steps = content["jobs"]["scrape"]["steps"]
        task_id_step = next(s for s in steps if s.get("id") == "task_id")
        self.assertIn("task_id=12", task_id_step["run"])

        run_step = next(s for s in steps if s.get("run") and "property_value_engine.py" in s.get("run", ""))
        self.assertIn("--suburbs", run_step["run"])

    def test_real_estate_scraper_auckland(self):
        path = os.path.join(self.workflows_dir, "real_estate_scraper_auckland.yml")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        self.assertEqual("scrape-realestate-auckland", content["jobs"]["scrape"]["concurrency"]["group"])

        steps = content["jobs"]["scrape"]["steps"]
        resume_step = next(s for s in steps if s.get("name", "").startswith("Trigger next run"))
        self.assertIn("real_estate_scraper_auckland.yml/dispatches", resume_step["run"])

    def test_real_estate_scraper_rent(self):
        path = os.path.join(self.workflows_dir, "real_estate_scraper_rent.yml")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        self.assertEqual("scrape-realestate-rent", content["jobs"]["scrape"]["concurrency"]["group"])

        steps = content["jobs"]["scrape"]["steps"]
        resume_step = next(s for s in steps if s.get("name", "").startswith("Trigger next run"))
        self.assertIn("real_estate_scraper_rent.yml/dispatches", resume_step["run"])

    def test_backfill_property_details(self):
        path = os.path.join(self.workflows_dir, "backfill_property_details.yml")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        self.assertEqual("backfill-property-details-${{ inputs.region || 'auckland' }}", content["jobs"]["backfill"]["concurrency"]["group"])

        steps = content["jobs"]["backfill"]["steps"]
        task_id_step = next(s for s in steps if s.get("id") == "task_id")
        self.assertIn("TASK_ID=15", task_id_step["run"])

        resume_step = next(s for s in steps if s.get("name", "").startswith("Trigger next run"))
        self.assertIn("backfill_property_details.yml/dispatches", resume_step["run"])

    def test_backfill_property_details_suburbs(self):
        path = os.path.join(self.workflows_dir, "backfill_property_details_suburbs.yml")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        self.assertEqual("backfill-property-details-suburbs-${{ inputs.region || 'auckland' }}", content["jobs"]["backfill"]["concurrency"]["group"])

        steps = content["jobs"]["backfill"]["steps"]
        task_id_step = next(s for s in steps if s.get("id") == "task_id")
        self.assertIn("TASK_ID=17", task_id_step["run"])

        resume_step = next(s for s in steps if s.get("name", "").startswith("Trigger next run"))
        self.assertIn("backfill_property_details_suburbs.yml/dispatches", resume_step["run"])

    def test_master_scheduler_exists(self):
        path = os.path.join(self.workflows_dir, "master_scheduler.yml")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)
        triggers = content.get("on") or content.get(True)
        self.assertTrue("schedule" in triggers or "workflow_dispatch" in triggers)

if __name__ == "__main__":
    unittest.main()
