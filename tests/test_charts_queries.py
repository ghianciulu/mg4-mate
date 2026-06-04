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


class TestGetMonthlyChargeCosts(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        con = sqlite3.connect(self._tmp.name)
        _base_schema(con)
        con.executescript("""
            CREATE TABLE charges (
                id INTEGER PRIMARY KEY,
                vehicle_id INTEGER,
                started_at TEXT,
                ended_at TEXT,
                location_type TEXT,
                max_power_kw REAL,
                cost REAL,
                energy_added_kwh REAL
            );
            INSERT INTO charges VALUES (1,1,'2026-05-10 20:00','2026-05-10 22:00','HOME',7.4,1.50,10.2);
            INSERT INTO charges VALUES (2,1,'2026-05-15 12:00','2026-05-15 13:00',NULL,11.0,2.20,15.0);
            INSERT INTO charges VALUES (3,1,'2026-06-01 21:00','2026-06-01 23:00','HOME',7.4,1.80,12.0);
            INSERT INTO charges VALUES (4,1,'2026-06-02 08:00',NULL,'HOME',7.4,NULL,NULL);
        """)
        con.commit()
        con.close()
        import db_reader
        db_reader.DB_PATH = self._tmp.name
        for attr in ("_ro_conn", "_rw_conn"):
            conn = getattr(db_reader, attr, None)
            if conn:
                try: conn.close()
                except Exception: pass
            setattr(db_reader, attr, None)
        self.dr = db_reader

    def tearDown(self):
        import db_reader
        for attr in ("_ro_conn", "_rw_conn"):
            conn = getattr(db_reader, attr, None)
            if conn:
                try: conn.close()
                except Exception: pass
            setattr(db_reader, attr, None)
        os.unlink(self._tmp.name)

    def test_returns_list(self):
        self.assertIsInstance(self.dr.get_monthly_charge_costs(), list)

    def test_excludes_open_charges(self):
        months = [r["month"] for r in self.dr.get_monthly_charge_costs()]
        self.assertIn("2026-05", months)
        self.assertIn("2026-06", months)

    def test_may_home_cost(self):
        result = self.dr.get_monthly_charge_costs()
        row = next((r for r in result if r["month"] == "2026-05" and r["charge_type"] == "HOME"), None)
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["total_cost"], 1.50, places=2)

    def test_infers_type_from_power(self):
        result = self.dr.get_monthly_charge_costs()
        row = next((r for r in result if r["month"] == "2026-05" and r["charge_type"] == "AC"), None)
        self.assertIsNotNone(row, "Should infer AC type from max_power_kw=11")


class TestGetEfficiencyVsTemp(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        con = sqlite3.connect(self._tmp.name)
        _base_schema(con)
        con.executescript("""
            CREATE TABLE trips (
                id INTEGER PRIMARY KEY,
                vehicle_id INTEGER,
                started_at TEXT,
                ended_at TEXT,
                distance_km REAL,
                efficiency_kwh_100km REAL
            );
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY,
                vehicle_id INTEGER,
                recorded_at TEXT,
                outside_temp REAL,
                soc REAL
            );
            INSERT INTO positions VALUES (1,1,'2026-05-01 08:55:00',15.0,80.0);
            INSERT INTO trips VALUES (1,1,'2026-05-01 09:00:00','2026-05-01 09:30:00',20.0,18.5);
            INSERT INTO trips VALUES (2,1,'2026-01-01 08:00:00','2026-01-01 08:30:00',5.0,22.0);
            INSERT INTO trips VALUES (3,1,'2026-05-02 10:00:00','2026-05-02 10:05:00',1.0,15.0);
            INSERT INTO trips VALUES (4,1,'2026-05-03 11:00:00','2026-05-03 11:30:00',15.0,NULL);
        """)
        con.commit()
        con.close()
        import db_reader
        db_reader.DB_PATH = self._tmp.name
        for attr in ("_ro_conn", "_rw_conn"):
            conn = getattr(db_reader, attr, None)
            if conn:
                try: conn.close()
                except Exception: pass
            setattr(db_reader, attr, None)
        self.dr = db_reader

    def tearDown(self):
        import db_reader
        for attr in ("_ro_conn", "_rw_conn"):
            conn = getattr(db_reader, attr, None)
            if conn:
                try: conn.close()
                except Exception: pass
            setattr(db_reader, attr, None)
        os.unlink(self._tmp.name)

    def test_returns_list(self):
        self.assertIsInstance(self.dr.get_efficiency_vs_temp(), list)

    def test_excludes_no_temp(self):
        ids = [r["id"] for r in self.dr.get_efficiency_vs_temp()]
        self.assertNotIn(2, ids)

    def test_excludes_short_trips(self):
        ids = [r["id"] for r in self.dr.get_efficiency_vs_temp()]
        self.assertNotIn(3, ids)

    def test_excludes_no_efficiency(self):
        ids = [r["id"] for r in self.dr.get_efficiency_vs_temp()]
        self.assertNotIn(4, ids)

    def test_correct_temp_lookup(self):
        result = self.dr.get_efficiency_vs_temp()
        trip1 = next((r for r in result if r["id"] == 1), None)
        self.assertIsNotNone(trip1)
        self.assertAlmostEqual(trip1["outside_temp"], 15.0, places=1)
        self.assertAlmostEqual(trip1["efficiency"], 18.5, places=1)


class TestGetTripPaths(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        con = sqlite3.connect(self._tmp.name)
        _base_schema(con)
        con.executescript("""
            CREATE TABLE trips (
                id INTEGER PRIMARY KEY,
                vehicle_id INTEGER,
                started_at TEXT,
                ended_at TEXT,
                distance_km REAL,
                efficiency_kwh_100km REAL
            );
            CREATE TABLE trip_positions (
                id INTEGER PRIMARY KEY,
                trip_id INTEGER,
                latitude REAL,
                longitude REAL,
                recorded_at TEXT
            );
            INSERT INTO trips VALUES (1,1,'2026-05-01 09:00','2026-05-01 09:30',20.0,18.5);
            INSERT INTO trip_positions VALUES (1,1,45.1,9.1,'2026-05-01 09:00');
            INSERT INTO trip_positions VALUES (2,1,45.2,9.2,'2026-05-01 09:15');
            INSERT INTO trip_positions VALUES (3,1,45.3,9.3,'2026-05-01 09:30');
            INSERT INTO trips VALUES (2,1,'2026-05-02 10:00','2026-05-02 10:05',1.5,NULL);
            INSERT INTO trip_positions VALUES (4,2,46.0,10.0,'2026-05-02 10:00');
            INSERT INTO trips VALUES (3,1,'2026-05-03 11:00',NULL,0.0,NULL);
            INSERT INTO trip_positions VALUES (5,3,47.0,11.0,'2026-05-03 11:00');
            INSERT INTO trip_positions VALUES (6,3,47.1,11.1,'2026-05-03 11:05');
        """)
        con.commit()
        con.close()
        import db_reader
        db_reader.DB_PATH = self._tmp.name
        for attr in ("_ro_conn", "_rw_conn"):
            conn = getattr(db_reader, attr, None)
            if conn:
                try: conn.close()
                except Exception: pass
            setattr(db_reader, attr, None)
        self.dr = db_reader

    def tearDown(self):
        import db_reader
        for attr in ("_ro_conn", "_rw_conn"):
            conn = getattr(db_reader, attr, None)
            if conn:
                try: conn.close()
                except Exception: pass
            setattr(db_reader, attr, None)
        os.unlink(self._tmp.name)

    def test_returns_list(self):
        self.assertIsInstance(self.dr.get_trip_paths(), list)

    def test_excludes_single_position_trip(self):
        ids = [r["trip_id"] for r in self.dr.get_trip_paths()]
        self.assertNotIn(2, ids)

    def test_excludes_open_trip(self):
        ids = [r["trip_id"] for r in self.dr.get_trip_paths()]
        self.assertNotIn(3, ids)

    def test_trip1_correct_points(self):
        result = self.dr.get_trip_paths()
        trip1 = next((r for r in result if r["trip_id"] == 1), None)
        self.assertIsNotNone(trip1)
        self.assertEqual(len(trip1["points"]), 3)
        self.assertEqual(trip1["points"][0], [45.1, 9.1])
        self.assertAlmostEqual(trip1["efficiency"], 18.5, places=1)
