import pathlib
import sqlite3
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "poller"))

from db import Database
from ha_history import HistoryImporter, history_to_snapshots


PREFIX = "lsjwh4097rn111393"


def h(entity_id, state, ts, **attributes):
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes,
        "last_updated": ts,
        "last_changed": ts,
    }


class HomeAssistantHistoryTest(unittest.TestCase):
    def test_history_to_snapshots_emits_chronological_vehicle_data(self):
        history = [
            [
                h(f"sensor.{PREFIX}_soc", "50", "2026-06-01T10:00:00+00:00"),
                h(f"sensor.{PREFIX}_soc", "49", "2026-06-01T10:02:00+00:00"),
            ],
            [
                h(f"sensor.{PREFIX}_mileage", "1000", "2026-06-01T10:00:00+00:00"),
                h(f"sensor.{PREFIX}_mileage", "1001", "2026-06-01T10:02:00+00:00"),
            ],
            [
                h(f"sensor.{PREFIX}_vehicle_speed", "0", "2026-06-01T10:00:00+00:00"),
                h(f"sensor.{PREFIX}_vehicle_speed", "42", "2026-06-01T10:01:00+00:00"),
            ],
            [
                h(
                    f"device_tracker.{PREFIX}_vehicle_position",
                    "not_home",
                    "2026-06-01T10:00:30+00:00",
                    latitude=38.1,
                    longitude=15.5,
                ),
                h(
                    f"device_tracker.{PREFIX}_vehicle_position",
                    "not_home",
                    "2026-06-01T10:02:00+00:00",
                    latitude=38.2,
                    longitude=15.6,
                ),
            ],
            [
                h(f"binary_sensor.{PREFIX}_vehicle_running", "off", "2026-06-01T10:00:00+00:00"),
                h(f"binary_sensor.{PREFIX}_vehicle_running", "on", "2026-06-01T10:01:00+00:00"),
            ],
        ]

        snapshots = history_to_snapshots(history, PREFIX)

        self.assertGreaterEqual(len(snapshots), 2)
        self.assertEqual([s.recorded_at for s in snapshots], sorted(s.recorded_at for s in snapshots))
        self.assertEqual(snapshots[-1].data.soc, 49.0)
        self.assertEqual(snapshots[-1].data.odometer_km, 1001.0)
        self.assertEqual(snapshots[-1].data.speed_kmh, 42.0)
        self.assertEqual(snapshots[-1].data.vehicle_state, "driving")
        self.assertEqual(snapshots[-1].data.latitude, 38.2)

    def test_import_skips_duplicate_positions(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        tmp.close()
        db = Database(db_path)
        vehicle_id = db.ensure_vehicle(PREFIX.upper(), "MG4")
        history = [
            [h(f"sensor.{PREFIX}_soc", "50", "2026-06-01T10:00:00+00:00")],
            [h(f"sensor.{PREFIX}_mileage", "1000", "2026-06-01T10:00:00+00:00")],
            [h(f"sensor.{PREFIX}_vehicle_speed", "0", "2026-06-01T10:00:00+00:00")],
            [
                h(
                    f"device_tracker.{PREFIX}_vehicle_position",
                    "home",
                    "2026-06-01T10:00:00+00:00",
                    latitude=38.1,
                    longitude=15.5,
                )
            ],
        ]

        importer = HistoryImporter(db, vehicle_id, PREFIX)
        first = importer.import_history(history)
        second = importer.import_history(history)

        conn = sqlite3.connect(db_path)
        self.assertEqual(first["positions"], 1)
        self.assertEqual(second["positions"], 0)
        self.assertEqual(conn.execute("select count(*) from positions").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
