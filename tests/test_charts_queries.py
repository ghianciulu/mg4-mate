"""Tests for the four chart query functions in web/db_reader.py."""
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))


def _base_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS vehicles (id INTEGER PRIMARY KEY, vin TEXT, car_type TEXT);
        INSERT OR IGNORE INTO settings VALUES ('setup_complete', '1');
    """)


def _reset(db_reader_mod) -> None:
    for attr in ("_ro_conn", "_rw_conn"):
        conn = getattr(db_reader_mod, attr, None)
        if conn:
            try: conn.close()
            except Exception: pass
        setattr(db_reader_mod, attr, None)


class TestGetSocHistory(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        con = sqlite3.connect(self._tmp.name)
        _base_schema(con)
        con.executescript("""
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY,
                vehicle_id INTEGER,
                recorded_at TEXT,
                soc REAL
            );
            -- Two readings in the same hour → should average to 60.0
            INSERT INTO positions VALUES (1, 1, '2026-05-01 08:00:00', 50.0);
            INSERT INTO positions VALUES (2, 1, '2026-05-01 08:30:00', 70.0);
            -- One reading in a different hour
            INSERT INTO positions VALUES (3, 1, '2026-05-01 09:00:00', 80.0);
            -- NULL soc — must be excluded
            INSERT INTO positions VALUES (4, 1, '2026-05-01 10:00:00', NULL);
        """)
        con.commit()
        con.close()

        import db_reader
        db_reader.DB_PATH = self._tmp.name
        _reset(db_reader)
        self.dr = db_reader

    def tearDown(self):
        import db_reader
        _reset(db_reader)
        os.unlink(self._tmp.name)

    def test_returns_list(self):
        result = self.dr.get_soc_history(days=0)
        self.assertIsInstance(result, list)

    def test_excludes_null_soc(self):
        result = self.dr.get_soc_history(days=0)
        self.assertEqual(len(result), 2, "Expected 2 hourly buckets (NULL excluded)")

    def test_hourly_average(self):
        result = self.dr.get_soc_history(days=0)
        hours = {r["hour"]: r["avg_soc"] for r in result}
        self.assertIn("2026-05-01T08:00:00", hours)
        self.assertAlmostEqual(hours["2026-05-01T08:00:00"], 60.0, places=1)

    def test_days_filter(self):
        # days=1 means last 1 day; all rows are old, should return empty
        result = self.dr.get_soc_history(days=1)
        self.assertEqual(result, [])
