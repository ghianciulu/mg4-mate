"""Tests for ghost trip detection (odometer jump while parked)."""
import pathlib
import sys
import tempfile
import os
import unittest
from unittest.mock import MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "poller"))


def _make_data(odometer_km=50000.0, vehicle_state="parked", speed_kmh=0.0,
               charging_status=0, plug_connected=False, soc=80.0,
               latitude=48.0, longitude=11.0):
    """Build a minimal VehicleData-like mock."""
    d = MagicMock()
    d.odometer_km = odometer_km
    d.vehicle_state = vehicle_state
    d.speed_kmh = speed_kmh
    d.charging_status = charging_status
    d.plug_connected = plug_connected
    d.soc = soc
    d.latitude = latitude
    d.longitude = longitude
    d.outside_temp = 20.0
    d.inside_temp = 22.0
    d.climate_target_temp = None
    d.battery_min_temp = None
    d.range_km = 200.0
    d.gear = "P"
    d.is_locked = True
    d.climate_on = False
    d.climate_cooling = False
    d.climate_heating = False
    d.climate_defrost = False
    d.trunk_open = False
    d.windows_open = False
    d.sunshade_open = False
    d.remaining_charge_min = None
    d.charge_voltage_v = None
    d.charge_current_a = 0.0
    d.charge_power_kw = 0.0
    d.door_fl_open = False
    d.door_fr_open = False
    d.door_rl_open = False
    d.door_rr_open = False
    d.bonnet_open = False
    d.aux_battery_v = None
    d.lights_dipped = False
    d.lights_main = False
    d.lights_side = False
    d.heading_deg = None
    d.tyre_fl_bar = None
    d.tyre_fr_bar = None
    d.tyre_rl_bar = None
    d.tyre_rr_bar = None
    return d


class TestGhostTripDetection(unittest.TestCase):

    def setUp(self):
        from db import Database
        from recorder import Recorder

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db = Database(self._tmp.name)
        self._vehicle_id = self._db.ensure_vehicle("TESTVIN001", "MG4", 2023)
        self._rec = Recorder(self._db, self._vehicle_id)

    def tearDown(self):
        self._db.close()
        os.unlink(self._tmp.name)

    def _count_trips(self):
        row = self._db._conn.execute("SELECT COUNT(*) AS n FROM trips").fetchone()
        return row["n"]

    def _get_trips(self):
        rows = self._db._conn.execute("SELECT * FROM trips ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def test_ghost_trip_created_when_odometer_jumps(self):
        """Odometer jumps 2 km while PARKED → ghost trip is created."""
        # First poll: parked, odo = 50000
        data1 = _make_data(odometer_km=50000.0)
        self._rec.process(data1)

        # Add a second position so get_last_position_recorded_at returns something
        data2 = _make_data(odometer_km=50000.0)
        self._rec.process(data2)

        # Third poll: still parked, odo jumped 2 km (ghost trip)
        data3 = _make_data(odometer_km=50002.0)
        self._rec.process(data3)

        trips = self._get_trips()
        self.assertEqual(len(trips), 1, "Expected exactly one ghost trip to be created")
        self.assertAlmostEqual(trips[0]["distance_km"], 2.0, places=2)

    def test_no_ghost_trip_below_threshold(self):
        """Odometer jumps only 0.3 km (below 0.5 km threshold) → no ghost trip."""
        data1 = _make_data(odometer_km=50000.0)
        self._rec.process(data1)

        data2 = _make_data(odometer_km=50000.3)
        self._rec.process(data2)

        self.assertEqual(self._count_trips(), 0, "No ghost trip should be created for sub-threshold jump")

    def test_ghost_trip_has_untracked_flag(self):
        """Ghost trip must have untracked=1 in the DB."""
        data1 = _make_data(odometer_km=50000.0)
        self._rec.process(data1)

        data2 = _make_data(odometer_km=50000.0)
        self._rec.process(data2)

        data3 = _make_data(odometer_km=50003.5)
        self._rec.process(data3)

        trips = self._get_trips()
        self.assertEqual(len(trips), 1)
        self.assertEqual(trips[0]["untracked"], 1, "Ghost trip must have untracked=1")


class TestCreateGhostTripDirect(unittest.TestCase):
    """Unit tests for the DB method itself."""

    def setUp(self):
        from db import Database
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db = Database(self._tmp.name)
        self._vehicle_id = self._db.ensure_vehicle("TESTVIN002", "MG4", 2023)

    def tearDown(self):
        self._db.close()
        os.unlink(self._tmp.name)

    def test_create_ghost_trip_returns_id(self):
        trip_id = self._db.create_ghost_trip(
            self._vehicle_id, 5.2,
            "2026-06-05T10:00:00+00:00",
            "2026-06-05T10:30:00+00:00",
        )
        self.assertIsInstance(trip_id, int)
        self.assertGreater(trip_id, 0)

    def test_create_ghost_trip_distance_stored(self):
        self._db.create_ghost_trip(
            self._vehicle_id, 7.8,
            "2026-06-05T10:00:00+00:00",
            "2026-06-05T10:45:00+00:00",
        )
        row = self._db._conn.execute(
            "SELECT distance_km, untracked FROM trips WHERE vehicle_id=?",
            (self._vehicle_id,)
        ).fetchone()
        self.assertAlmostEqual(row["distance_km"], 7.8, places=2)
        self.assertEqual(row["untracked"], 1)


if __name__ == "__main__":
    unittest.main()
