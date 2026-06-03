"""Regression tests for web/db_reader.py — get_trips_grouped()."""
import pathlib
import sqlite3
import sys
import tempfile
import os
import unittest
from collections import OrderedDict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))


def _make_db(path: str) -> None:
    """Create a minimal schema and insert 3 trips across 2 days."""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE trips (
            id              INTEGER PRIMARY KEY,
            started_at      TEXT,
            ended_at        TEXT,
            distance_km     REAL,
            duration_min    REAL,
            efficiency_kwh_100km REAL,
            start_soc       REAL,
            end_soc         REAL,
            regen_kwh       REAL
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE vehicles  (id INTEGER PRIMARY KEY, vin TEXT, car_type TEXT);
        INSERT INTO settings VALUES ('setup_complete', '1');
        -- Two trips on 2026-06-01, one on 2026-06-02
        INSERT INTO trips VALUES (1, '2026-06-01 08:00:00', '2026-06-01 08:30:00',
                                  20.0, 30, 16.0, 80, 70, 0.5);
        INSERT INTO trips VALUES (2, '2026-06-01 17:00:00', '2026-06-01 17:45:00',
                                  25.0, 45, 18.0, 65, 52, 0.8);
        INSERT INTO trips VALUES (3, '2026-06-02 09:00:00', '2026-06-02 09:40:00',
                                  30.0, 40, 20.0, 90, 75, 1.0);
    """)
    con.commit()
    con.close()


class TestGetTripsGrouped(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        _make_db(self._tmp.name)

        # Point db_reader at the temp DB and reset cached connections
        import db_reader
        db_reader.DB_PATH = self._tmp.name
        db_reader._ro_conn = None
        db_reader._rw_conn = None
        self.db_reader = db_reader

    def tearDown(self):
        import db_reader
        if db_reader._ro_conn:
            db_reader._ro_conn.close()
            db_reader._ro_conn = None
        if db_reader._rw_conn:
            db_reader._rw_conn.close()
            db_reader._rw_conn = None
        os.unlink(self._tmp.name)

    def test_returns_list_of_year_nodes(self):
        result = self.db_reader.get_trips_grouped()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1, "Expected exactly 1 year node")

    def test_year_node_has_required_keys(self):
        year = self.db_reader.get_trips_grouped()[0]
        for key in ("label", "km", "count", "avg_eff", "months"):
            self.assertIn(key, year, f"year node missing key: {key!r}")

    def test_year_label_and_totals(self):
        year = self.db_reader.get_trips_grouped()[0]
        self.assertEqual(year["label"], "2026")
        self.assertEqual(year["count"], 3)
        self.assertAlmostEqual(year["km"], 75.0, places=1)

    def test_months_is_dict_with_values_method(self):
        """months must support .values() — the template iterates month.months.values()."""
        year = self.db_reader.get_trips_grouped()[0]
        self.assertTrue(
            hasattr(year["months"], "values"),
            "year.months must be a dict/OrderedDict, not a list",
        )

    def test_month_node_has_required_keys(self):
        year = self.db_reader.get_trips_grouped()[0]
        month = next(iter(year["months"].values()))
        for key in ("label", "km", "count", "avg_eff", "days"):
            self.assertIn(key, month, f"month node missing key: {key!r}")

    def test_month_label_format(self):
        """Month label must be human-readable like 'June 2026', not '2026-06'."""
        year = self.db_reader.get_trips_grouped()[0]
        month = next(iter(year["months"].values()))
        self.assertEqual(month["label"], "June 2026")

    def test_days_is_dict_with_values_method(self):
        """days must support .values() — the template iterates month.days.values()."""
        year = self.db_reader.get_trips_grouped()[0]
        month = next(iter(year["months"].values()))
        self.assertTrue(
            hasattr(month["days"], "values"),
            "month.days must be a dict/OrderedDict, not a list",
        )

    def test_day_node_has_required_keys(self):
        year = self.db_reader.get_trips_grouped()[0]
        month = next(iter(year["months"].values()))
        day = next(iter(month["days"].values()))
        for key in ("label", "km", "count", "avg_eff", "trips"):
            self.assertIn(key, day, f"day node missing key: {key!r}")

    def test_day_label_format(self):
        """Day label must be '01 Jun 2026' format."""
        year = self.db_reader.get_trips_grouped()[0]
        month = next(iter(year["months"].values()))
        # days are ordered DESC; first key is the latest day
        day_labels = [d["label"] for d in month["days"].values()]
        self.assertIn("01 Jun 2026", day_labels)
        self.assertIn("02 Jun 2026", day_labels)

    def test_two_days_in_june(self):
        year = self.db_reader.get_trips_grouped()[0]
        month = next(iter(year["months"].values()))
        self.assertEqual(len(month["days"]), 2)

    def test_day_with_two_trips_has_correct_count(self):
        year = self.db_reader.get_trips_grouped()[0]
        month = next(iter(year["months"].values()))
        # Find the June-01 day (2 trips)
        day_01 = None
        for d in month["days"].values():
            if d["label"] == "01 Jun 2026":
                day_01 = d
                break
        self.assertIsNotNone(day_01, "Day '01 Jun 2026' not found")
        self.assertEqual(day_01["count"], 2)
        self.assertAlmostEqual(day_01["km"], 45.0, places=1)

    def test_day_trips_list_contains_full_trip_dicts(self):
        year = self.db_reader.get_trips_grouped()[0]
        month = next(iter(year["months"].values()))
        day_01 = next(d for d in month["days"].values() if d["label"] == "01 Jun 2026")
        self.assertEqual(len(day_01["trips"]), 2)
        trip = day_01["trips"][0]
        # Must have fields the template accesses
        for field in ("id", "started_at", "ended_at", "distance_km",
                      "duration_min", "efficiency_kwh_100km", "start_soc", "end_soc"):
            self.assertIn(field, trip, f"trip dict missing field: {field!r}")

    def test_avg_eff_key_not_avg_efficiency(self):
        """Key must be 'avg_eff', not 'avg_efficiency'."""
        year = self.db_reader.get_trips_grouped()[0]
        self.assertIn("avg_eff", year)
        self.assertNotIn("avg_efficiency", year)
        month = next(iter(year["months"].values()))
        self.assertIn("avg_eff", month)
        self.assertNotIn("avg_efficiency", month)
        day = next(iter(month["days"].values()))
        self.assertIn("avg_eff", day)
        self.assertNotIn("avg_efficiency", day)


class TestMergeTrips(unittest.TestCase):
    """Tests for merge_trips() — verifies DB writes and ro_conn cache invalidation."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        con = sqlite3.connect(self._tmp.name)
        con.executescript("""
            CREATE TABLE trips (
                id                   INTEGER PRIMARY KEY,
                vehicle_id           INTEGER,
                started_at           TEXT,
                ended_at             TEXT,
                start_soc            REAL,
                end_soc              REAL,
                distance_km          REAL,
                duration_min         REAL,
                efficiency_kwh_100km REAL,
                regen_kwh            REAL,
                start_odometer_km    REAL,
                end_odometer_km      REAL
            );
            CREATE TABLE trip_positions (
                id         INTEGER PRIMARY KEY,
                trip_id    INTEGER,
                latitude   REAL,
                longitude  REAL,
                speed_kmh  REAL,
                soc        REAL
            );
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE vehicles  (id INTEGER PRIMARY KEY, vin TEXT, car_type TEXT);
            INSERT INTO settings VALUES ('setup_complete', '1');
            INSERT INTO trips VALUES (1, 1,
                '2026-06-01 10:00:00', '2026-06-01 10:20:00',
                80, 70, 15.0, 20, 18.0, 0.5, 1000, 1015);
            INSERT INTO trips VALUES (2, 1,
                '2026-06-01 10:35:00', '2026-06-01 10:55:00',
                68, 55, 12.0, 20, 19.0, 0.4, 1015, 1027);
            INSERT INTO trip_positions VALUES (1, 1, 51.5, 0.1, 50.0, 78.0);
            INSERT INTO trip_positions VALUES (2, 1, 51.6, 0.2, 60.0, 75.0);
            INSERT INTO trip_positions VALUES (3, 2, 51.7, 0.3, 55.0, 66.0);
        """)
        con.commit()
        con.close()

        import db_reader
        db_reader.DB_PATH = self._tmp.name
        db_reader._ro_conn = None
        db_reader._rw_conn = None
        self.db_reader = db_reader

    def tearDown(self):
        import db_reader
        for attr in ("_ro_conn", "_rw_conn"):
            conn = getattr(db_reader, attr, None)
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            setattr(db_reader, attr, None)
        os.unlink(self._tmp.name)

    def test_merge_returns_non_empty_dict(self):
        result = self.db_reader.merge_trips(1, 2)
        self.assertIsInstance(result, dict)
        self.assertTrue(result, "merge_trips() returned empty dict")

    def test_merged_distance_is_sum(self):
        result = self.db_reader.merge_trips(1, 2)
        self.assertAlmostEqual(result["distance_km"], 27.0, places=1)

    def test_merged_regen_is_sum(self):
        result = self.db_reader.merge_trips(1, 2)
        self.assertAlmostEqual(result["regen_kwh"], 0.9, places=2)

    def test_merged_end_matches_dropped_trip(self):
        result = self.db_reader.merge_trips(1, 2)
        self.assertEqual(result["ended_at"], "2026-06-01 10:55:00")
        self.assertAlmostEqual(result["end_soc"], 55.0, places=1)
        self.assertAlmostEqual(result["end_odometer_km"], 1027.0, places=1)

    def test_dropped_trip_is_gone(self):
        self.db_reader.merge_trips(1, 2)
        con = sqlite3.connect(self._tmp.name)
        rows = con.execute("SELECT id FROM trips").fetchall()
        con.close()
        ids = [r[0] for r in rows]
        self.assertIn(1, ids)
        self.assertNotIn(2, ids, "Dropped trip 2 still exists after merge")

    def test_positions_reassigned_to_kept_trip(self):
        self.db_reader.merge_trips(1, 2)
        con = sqlite3.connect(self._tmp.name)
        rows = con.execute("SELECT trip_id FROM trip_positions").fetchall()
        con.close()
        trip_ids = {r[0] for r in rows}
        self.assertEqual(trip_ids, {1}, "All positions should belong to trip 1")

    def test_ro_conn_reset_after_merge(self):
        """After merge_trips(), _ro_conn must be None so next read sees fresh data."""
        # Force a read so _ro_conn gets populated
        _ = self.db_reader.get_trip_detail(1)
        self.assertIsNotNone(self.db_reader._ro_conn)
        # Merge — should reset _ro_conn
        self.db_reader.merge_trips(1, 2)
        self.assertIsNone(self.db_reader._ro_conn,
                          "_ro_conn should be reset to None after merge_trips()")

    def test_get_trip_detail_sees_merged_data(self):
        """get_trip_detail() after merge must return merged distance, not old value."""
        # Prime the ro_conn cache with the pre-merge state
        _ = self.db_reader.get_trip_detail(1)
        # Perform merge
        self.db_reader.merge_trips(1, 2)
        # Now read via the normal read path — must see updated data
        detail = self.db_reader.get_trip_detail(1)
        self.assertIsNotNone(detail)
        self.assertAlmostEqual(detail["distance_km"], 27.0, places=1,
                               msg="get_trip_detail() returned stale pre-merge data (WAL cache bug)")

    def test_merge_with_unknown_id_returns_empty(self):
        result = self.db_reader.merge_trips(1, 999)
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
