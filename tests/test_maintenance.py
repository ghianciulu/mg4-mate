"""Tests for DB migration runner and maintenance tracker."""
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "poller"))
sys.path.insert(0, str(ROOT / "web"))


class TestMigrationRunner(unittest.TestCase):

    def setUp(self):
        from db import Database
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db = Database(self._tmp.name)

    def tearDown(self):
        self._db.close()
        os.unlink(self._tmp.name)

    def test_schema_migrations_table_exists(self):
        row = self._db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        self.assertIsNotNone(row, "schema_migrations table must be created")

    def test_all_migrations_applied_on_fresh_db(self):
        from db import MIGRATIONS
        applied = {r[0] for r in self._db._conn.execute(
            "SELECT version FROM schema_migrations"
        ).fetchall()}
        for version, _ in MIGRATIONS:
            self.assertIn(version, applied, f"Migration {version} not recorded as applied")

    def test_migrations_idempotent(self):
        """Calling _apply_migrations() a second time must not raise or create duplicate rows."""
        from db import MIGRATIONS
        self._db._apply_migrations()
        count = self._db._conn.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0]
        self.assertEqual(count, len(MIGRATIONS), "Duplicate migration rows after second call")

    def test_positions_has_tyre_columns(self):
        cols = {r[1] for r in self._db._conn.execute(
            "PRAGMA table_info(positions)"
        ).fetchall()}
        for col in ("tyre_fl_bar", "tyre_fr_bar", "tyre_rl_bar", "tyre_rr_bar"):
            self.assertIn(col, cols, f"Column {col} missing from positions")

    def test_trips_has_untracked_column(self):
        cols = {r[1] for r in self._db._conn.execute(
            "PRAGMA table_info(trips)"
        ).fetchall()}
        self.assertIn("untracked", cols)


class TestMaintenanceSeeding(unittest.TestCase):

    def setUp(self):
        from db import Database
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db = Database(self._tmp.name)

    def tearDown(self):
        self._db.close()
        os.unlink(self._tmp.name)

    def test_maintenance_items_table_exists(self):
        row = self._db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='maintenance_items'"
        ).fetchone()
        self.assertIsNotNone(row)

    def test_maintenance_logs_table_exists(self):
        row = self._db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='maintenance_logs'"
        ).fetchone()
        self.assertIsNotNone(row)

    def test_mg4_schedule_seeded(self):
        count = self._db._conn.execute(
            "SELECT COUNT(*) FROM maintenance_items"
        ).fetchone()[0]
        self.assertGreaterEqual(count, 8, "Expected at least 8 MG4 service items")

    def test_seed_not_duplicated_on_second_init(self):
        from db import Database
        count_before = self._db._conn.execute(
            "SELECT COUNT(*) FROM maintenance_items"
        ).fetchone()[0]
        self._db.close()
        db2 = Database(self._tmp.name)
        count_after = db2._conn.execute(
            "SELECT COUNT(*) FROM maintenance_items"
        ).fetchone()[0]
        db2.close()
        self._db = db2  # so tearDown can close it
        self.assertEqual(count_before, count_after, "Seed must not insert duplicates")

    def test_maintenance_items_have_required_columns(self):
        cols = {r[1] for r in self._db._conn.execute(
            "PRAGMA table_info(maintenance_items)"
        ).fetchall()}
        for col in ("id", "title", "interval_km", "interval_months", "trigger_mode",
                    "last_done_km", "last_done_date"):
            self.assertIn(col, cols, f"Column {col} missing from maintenance_items")


class TestMaintenanceStatus(unittest.TestCase):
    """Pure-function tests for _maintenance_status — no DB needed."""

    def _item(self, **kwargs):
        base = {
            "id": 1, "title": "Test", "notes": None,
            "interval_km": 10_000, "interval_months": 12,
            "trigger_mode": "either",
            "last_done_km": 50_000.0,
            "last_done_date": "2025-01-01",
        }
        base.update(kwargs)
        return base

    def test_overdue_by_km(self):
        from db_reader import _maintenance_status
        item = self._item(interval_months=None, trigger_mode="km")
        result = _maintenance_status(item, current_km=61_500.0, now=datetime(2025, 6, 1))
        self.assertEqual(result["status"], "overdue")
        self.assertLess(result["km_remaining"], 0)

    def test_upcoming_by_km(self):
        from db_reader import _maintenance_status
        # 800 km left = 8% of 10 000 interval (threshold is 15%)
        item = self._item(interval_months=None, trigger_mode="km")
        result = _maintenance_status(item, current_km=59_200.0, now=datetime(2025, 6, 1))
        self.assertEqual(result["status"], "upcoming")

    def test_ok_by_km(self):
        from db_reader import _maintenance_status
        item = self._item(interval_months=None, trigger_mode="km")
        result = _maintenance_status(item, current_km=53_000.0, now=datetime(2025, 6, 1))
        self.assertEqual(result["status"], "ok")

    def test_overdue_by_months(self):
        from db_reader import _maintenance_status
        # last done 2023-01-01, interval 12 months → due 2024-01-01 → overdue by >12 months
        item = self._item(interval_km=None, trigger_mode="months",
                          last_done_date="2023-01-01", last_done_km=None)
        result = _maintenance_status(item, current_km=None, now=datetime(2025, 6, 1))
        self.assertEqual(result["status"], "overdue")
        self.assertLess(result["days_remaining"], 0)

    def test_upcoming_by_months(self):
        from db_reader import _maintenance_status
        # last done 340 days ago → due in ~25 days
        last_done = (datetime.now() - timedelta(days=340)).strftime("%Y-%m-%d")
        item = self._item(interval_km=None, trigger_mode="months",
                          last_done_date=last_done, last_done_km=None)
        result = _maintenance_status(item, current_km=None, now=datetime.now())
        self.assertEqual(result["status"], "upcoming")
        self.assertGreaterEqual(result["days_remaining"], 0)
        self.assertLessEqual(result["days_remaining"], 30)

    def test_either_overdue_when_km_overdue(self):
        from db_reader import _maintenance_status
        item = self._item(trigger_mode="either")
        # km overdue, months ok
        result = _maintenance_status(item, current_km=62_000.0, now=datetime(2025, 3, 1))
        self.assertEqual(result["status"], "overdue")

    def test_never_done_shows_no_status_data(self):
        from db_reader import _maintenance_status
        item = self._item(last_done_km=None, last_done_date=None)
        result = _maintenance_status(item, current_km=55_000.0, now=datetime.now())
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["km_remaining"])
        self.assertIsNone(result["days_remaining"])


class TestLogMaintenance(unittest.TestCase):

    def setUp(self):
        from db import Database
        import db_reader
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        # Use poller DB to create tables + seed
        db = Database(self._tmp.name)
        db.close()
        # Point web db_reader at the same file
        db_reader.DB_PATH = self._tmp.name
        db_reader._ro_conn = None
        db_reader._rw_conn = None
        self.db_reader = db_reader

    def tearDown(self):
        self.db_reader._ro_conn = None
        self.db_reader._rw_conn = None
        os.unlink(self._tmp.name)

    def test_log_maintenance_updates_last_done(self):
        items_before = self.db_reader.get_maintenance_items()
        first_item_id = items_before[0]["id"]

        self.db_reader.log_maintenance(
            first_item_id,
            odometer_km=55_000.0,
            cost=120.0,
            provider="SAIC Dealer",
            notes="Annual service",
        )

        items_after = self.db_reader.get_maintenance_items(current_km=55_000.0)
        updated = next(i for i in items_after if i["id"] == first_item_id)
        self.assertEqual(updated["last_done_km"], 55_000.0)
        self.assertIsNotNone(updated["last_done_date"])

    def test_log_maintenance_creates_log_record(self):
        items = self.db_reader.get_maintenance_items()
        item_id = items[0]["id"]

        self.db_reader.log_maintenance(item_id, 55_000.0, 80.0, "Test Shop", "")
        logs = self.db_reader.get_maintenance_logs(item_id=item_id)
        self.assertEqual(len(logs), 1)
        self.assertAlmostEqual(logs[0]["odometer_km"], 55_000.0)
        self.assertAlmostEqual(logs[0]["cost"], 80.0)
