"""Tests for trip continuity edge cases:
- stale open trip is not resumed at startup when gap > merge window
- ghost trip is not used as merge candidate for the next real trip
"""
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "poller"))


def _make_data(vehicle_state="parked", speed_kmh=0.0, odometer_km=50000.0,
               charging_status=0, plug_connected=False, soc=80.0,
               latitude=48.0, longitude=11.0):
    d = MagicMock()
    d.vehicle_state = vehicle_state
    d.speed_kmh = speed_kmh
    d.odometer_km = odometer_km
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
    d.gear = "D" if vehicle_state == "driving" else "P"
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


class TestStaleTripNotResumed(unittest.TestCase):
    """When the addon restarts and finds an open trip whose last GPS activity
    is older than trip_merge_gap_min, it should close it as orphan and create
    a fresh trip for the current drive — not silently continue the old one."""

    def setUp(self):
        from db import Database
        from recorder import Recorder
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db = Database(self._tmp.name)
        self._vid = self._db.ensure_vehicle("STALEVIN", "MG4", 2023)

    def tearDown(self):
        self._db.close()
        os.unlink(self._tmp.name)

    def _inject_open_trip_with_old_position(self, minutes_ago: int) -> int:
        """Insert an open trip with 2 trip_positions timestamped `minutes_ago` in the past
        (2 points needed so close_orphan_trips closes rather than deletes the trip)."""
        old_ts  = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
        old_ts2 = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago - 1)).isoformat()
        cur = self._db._conn.execute(
            "INSERT INTO trips (vehicle_id, started_at) VALUES (?,?)",
            (self._vid, old_ts),
        )
        trip_id = cur.lastrowid
        for ts, lat in ((old_ts, 48.0), (old_ts2, 48.01)):
            self._db._conn.execute(
                "INSERT INTO trip_positions (trip_id, recorded_at, latitude, longitude, speed_kmh, soc)"
                " VALUES (?,?,?,?,?,?)",
                (trip_id, ts, lat, 11.0, 50.0, 80.0),
            )
        self._db._conn.commit()
        return trip_id

    def test_stale_open_trip_closed_on_restart_while_driving(self):
        """Open trip from 2 hours ago must not be resumed even if car is currently driving."""
        from recorder import Recorder
        old_trip_id = self._inject_open_trip_with_old_position(minutes_ago=120)

        rec = Recorder(self._db, self._vid)
        driving_data = _make_data(vehicle_state="driving", speed_kmh=50.0)
        rec.process(driving_data)

        # Old trip should now be closed (has an ended_at)
        old = self._db._conn.execute(
            "SELECT ended_at FROM trips WHERE id=?", (old_trip_id,)
        ).fetchone()
        self.assertIsNotNone(old["ended_at"], "Stale open trip must be closed as orphan")

        # A new separate trip should have been created
        trips = self._db._conn.execute(
            "SELECT id FROM trips ORDER BY id"
        ).fetchall()
        self.assertEqual(len(trips), 2, "Should have: 1 closed orphan + 1 new trip")
        self.assertNotEqual(trips[1]["id"], old_trip_id)

    def test_fresh_open_trip_resumed_on_restart_while_driving(self):
        """Open trip from 2 minutes ago (within merge window) must be resumed."""
        from recorder import Recorder
        fresh_trip_id = self._inject_open_trip_with_old_position(minutes_ago=2)

        rec = Recorder(self._db, self._vid)
        driving_data = _make_data(vehicle_state="driving", speed_kmh=50.0)
        rec.process(driving_data)

        # The old trip must still be open (resumed, not closed)
        old = self._db._conn.execute(
            "SELECT ended_at FROM trips WHERE id=?", (fresh_trip_id,)
        ).fetchone()
        self.assertIsNone(old["ended_at"], "Fresh open trip must be resumed, not closed")
        self.assertEqual(rec._active_trip_id, fresh_trip_id)


class TestGhostTripNotMergedWithNextTrip(unittest.TestCase):
    """A ghost trip (untracked=1) must not be used as a merge candidate when
    the next real driving session starts, even if it was just created."""

    def setUp(self):
        from db import Database
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db = Database(self._tmp.name)
        self._vid = self._db.ensure_vehicle("GHOSTVIN", "MG4", 2023)

    def tearDown(self):
        self._db.close()
        os.unlink(self._tmp.name)

    def test_ghost_trip_excluded_from_merge_candidates(self):
        """get_recent_ended_trip must not return a ghost trip."""
        now_iso = datetime.now(timezone.utc).isoformat()
        self._db.create_ghost_trip(self._vid, 3.0, now_iso, now_iso)

        result = self._db.get_recent_ended_trip(self._vid, within_seconds=300)
        self.assertIsNone(result, "Ghost trip must not be returned as a merge candidate")

    def test_real_trip_still_returned_as_merge_candidate(self):
        """get_recent_ended_trip must still return a normal (non-ghost) ended trip."""
        now_iso = datetime.now(timezone.utc).isoformat()
        cur = self._db._conn.execute(
            """INSERT INTO trips (vehicle_id, started_at, ended_at, distance_km, untracked)
               VALUES (?,?,?,?,0)""",
            (self._vid, now_iso, now_iso, 5.0),
        )
        self._db._conn.commit()
        real_id = cur.lastrowid

        result = self._db.get_recent_ended_trip(self._vid, within_seconds=300)
        self.assertIsNotNone(result, "Normal ended trip must be returned as merge candidate")
        self.assertEqual(result["id"], real_id)


if __name__ == "__main__":
    unittest.main()
