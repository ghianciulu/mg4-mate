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


if __name__ == "__main__":
    unittest.main()
