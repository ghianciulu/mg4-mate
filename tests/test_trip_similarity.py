"""Tests for trip similarity scorer."""
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))
sys.path.insert(0, str(ROOT / "poller"))


def _insert_trip(con, tid, started_at, distance_km, slat, slon, elat, elon, untracked=0):
    ended_at = started_at  # for test purposes
    con.execute(
        """INSERT INTO trips
           (id, vehicle_id, started_at, ended_at, distance_km,
            start_lat, start_lon, end_lat, end_lon, untracked)
           VALUES (?,1,?,?,?,?,?,?,?,?)""",
        (tid, started_at, ended_at, distance_km, slat, slon, elat, elon, untracked),
    )


def _make_db(path: str) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE trips (
            id INTEGER PRIMARY KEY, vehicle_id INTEGER,
            started_at TEXT, ended_at TEXT, distance_km REAL,
            start_lat REAL, start_lon REAL, end_lat REAL, end_lon REAL,
            start_soc REAL, end_soc REAL, efficiency_kwh_100km REAL,
            regen_kwh REAL, duration_min REAL, untracked INTEGER DEFAULT 0,
            start_odometer_km REAL, end_odometer_km REAL
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO settings VALUES ('setup_complete', '1');
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY, recorded_at TEXT,
            outside_temp REAL, soc REAL
        );
    """)
    # Target trip: home→work, 22 km, 08:15 local, Milan coords
    _insert_trip(con, 1, "2026-06-08T06:15:00+00:00", 22.0, 45.464, 9.188, 45.497, 9.213)
    # Similar trip: same route, 21.5 km, 08:30 local
    _insert_trip(con, 2, "2026-05-28T06:30:00+00:00", 21.5, 45.464, 9.188, 45.497, 9.213)
    # Different route: completely different end point
    _insert_trip(con, 3, "2026-06-01T06:15:00+00:00", 22.0, 45.464, 9.188, 45.600, 9.400)
    # Too different distance: 35 km (>40% more than 22)
    _insert_trip(con, 4, "2026-06-02T06:15:00+00:00", 35.0, 45.464, 9.188, 45.497, 9.213)
    # Ghost trip with same route: must be excluded
    _insert_trip(con, 5, "2026-06-03T06:15:00+00:00", 22.0, 45.464, 9.188, 45.497, 9.213,
                 untracked=1)
    con.commit()
    con.close()


class TestSimilarityScorer(unittest.TestCase):

    def setUp(self):
        import db_reader
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        _make_db(self._tmp.name)
        db_reader.DB_PATH   = self._tmp.name
        db_reader._ro_conn  = None
        db_reader._rw_conn  = None
        self.db_reader = db_reader

    def tearDown(self):
        self.db_reader._ro_conn = None
        self.db_reader._rw_conn = None
        os.unlink(self._tmp.name)

    def test_similar_trip_returned(self):
        results = self.db_reader.get_similar_trips(1, days=365)
        ids = [r["id"] for r in results]
        self.assertIn(2, ids, "Trip 2 (same route, close time) must be in results")

    def test_different_route_excluded(self):
        results = self.db_reader.get_similar_trips(1, days=365)
        ids = [r["id"] for r in results]
        self.assertNotIn(3, ids, "Trip 3 (different end point) must be excluded")

    def test_distance_gate_excludes_large_delta(self):
        results = self.db_reader.get_similar_trips(1, days=365)
        ids = [r["id"] for r in results]
        self.assertNotIn(4, ids, "Trip 4 (35 km vs 22 km = >40% delta) must be excluded")

    def test_ghost_trip_excluded(self):
        results = self.db_reader.get_similar_trips(1, days=365)
        ids = [r["id"] for r in results]
        self.assertNotIn(5, ids, "Ghost trip (untracked=1) must be excluded")

    def test_target_trip_not_in_results(self):
        results = self.db_reader.get_similar_trips(1, days=365)
        ids = [r["id"] for r in results]
        self.assertNotIn(1, ids, "Target trip must not appear in its own similar-trips list")

    def test_results_have_similarity_score(self):
        results = self.db_reader.get_similar_trips(1, days=365)
        for r in results:
            self.assertIn("similarity_score", r)
            self.assertGreaterEqual(r["similarity_score"], 30)
            self.assertLessEqual(r["similarity_score"],   100)

    def test_results_sorted_by_score_desc(self):
        results = self.db_reader.get_similar_trips(1, days=365)
        scores = [r["similarity_score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestSimilarityScoreFunction(unittest.TestCase):

    def _trip(self, slat, slon, elat, elon, dist, hour=8):
        return {
            "start_lat": slat, "start_lon": slon,
            "end_lat":   elat, "end_lon":   elon,
            "distance_km": dist,
            "started_at": f"2026-06-01T{hour:02d}:00:00+00:00",
        }

    def test_identical_coords_and_distance(self):
        from db_reader import _similarity_score
        t = self._trip(45.464, 9.188, 45.497, 9.213, 22.0)
        score = _similarity_score(t, t)
        self.assertGreaterEqual(score, 90)

    def test_missing_coords_returns_zero(self):
        from db_reader import _similarity_score
        t = self._trip(45.464, 9.188, 45.497, 9.213, 22.0)
        c = dict(t)
        c["start_lat"] = None
        self.assertEqual(_similarity_score(t, c), 0)

    def test_distance_too_small_returns_zero(self):
        from db_reader import _similarity_score
        t = self._trip(45.464, 9.188, 45.497, 9.213, 0.5)
        self.assertEqual(_similarity_score(t, t), 0)
