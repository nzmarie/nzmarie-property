import builtins
import importlib
import sys
import unittest
from unittest.mock import patch


class TestDatabaseOptionalPandas(unittest.TestCase):
    def test_import_succeeds_without_pandas(self):
        sys.modules.pop("utils.database", None)
        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "pandas":
                raise ModuleNotFoundError("No module named 'pandas'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            module = importlib.import_module("utils.database")
            self.assertTrue(hasattr(module, "DatabaseClient"))
            self.assertIsNone(module.pd)
            self.assertTrue(hasattr(module, "db"))

        sys.modules.pop("utils.database", None)


if __name__ == "__main__":
    unittest.main()
