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
