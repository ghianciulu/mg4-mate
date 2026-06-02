import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "poller"))

from ha_client import HomeAssistantMateClient


PREFIX = "lsjwh4097rn111393"


def state(entity_id, state, **attributes):
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes,
        "last_updated": "2026-06-01T16:59:44.000000+00:00",
    }


class HomeAssistantMateClientTest(unittest.TestCase):
    def test_maps_home_assistant_states_to_vehicle_data(self):
        client = HomeAssistantMateClient(
            ha_url="https://example.invalid",
            token="secret",
            entity_prefix=PREFIX,
            fetch_states=lambda: [
                state(f"sensor.{PREFIX}_soc", "40.7"),
                state(f"sensor.{PREFIX}_range", "164.0"),
                state(f"sensor.{PREFIX}_mileage", "10181.0"),
                state(f"sensor.{PREFIX}_vehicle_speed", "0.0"),
                state(f"sensor.{PREFIX}_exterior_temperature", "28"),
                state(f"sensor.{PREFIX}_interior_temperature", "27"),
                state(f"sensor.{PREFIX}_power", "0.0"),
                state(f"sensor.{PREFIX}_voltage", "380.75"),
                state(f"sensor.{PREFIX}_current", "0.0"),
                state(f"sensor.{PREFIX}_remaining_charging_time", "0"),
                state(f"sensor.{PREFIX}_total_battery_capacity", "64.0"),
                state(f"binary_sensor.{PREFIX}_vehicle_running", "off"),
                state(f"binary_sensor.{PREFIX}_battery_charging", "off"),
                state(f"binary_sensor.{PREFIX}_charger_connected", "off"),
                state(f"binary_sensor.{PREFIX}_door_driver", "off"),
                state(f"binary_sensor.{PREFIX}_boot", "off"),
                state(f"binary_sensor.{PREFIX}_window_driver", "off"),
                state(f"lock.{PREFIX}_doors_lock", "locked"),
                state(
                    f"device_tracker.{PREFIX}_vehicle_position",
                    "home",
                    latitude=38.173509,
                    longitude=15.541493,
                ),
            ],
        )

        client.login()
        data = client.get_status()

        self.assertEqual(data.vin, PREFIX.upper())
        self.assertEqual(data.soc, 40.7)
        self.assertEqual(data.range_km, 164.0)
        self.assertEqual(data.odometer_km, 10181.0)
        self.assertEqual(data.vehicle_state, "parked")
        self.assertEqual(data.gear, "P")
        self.assertEqual(data.latitude, 38.173509)
        self.assertEqual(data.longitude, 15.541493)
        self.assertFalse(data.is_locked is False)
        self.assertFalse(data.charging_status)
        self.assertFalse(data.plug_connected)

    def test_maps_charging_snapshot_to_charging_vehicle_data(self):
        client = HomeAssistantMateClient(
            ha_url="https://example.invalid",
            token="secret",
            entity_prefix=PREFIX,
            fetch_states=lambda: [
                state(f"sensor.{PREFIX}_soc", "51.0"),
                state(f"sensor.{PREFIX}_range", "205.0"),
                state(f"sensor.{PREFIX}_mileage", "10181.0"),
                state(f"sensor.{PREFIX}_vehicle_speed", "0.0"),
                state(f"sensor.{PREFIX}_power", "-6.4"),
                state(f"sensor.{PREFIX}_voltage", "380.0"),
                state(f"sensor.{PREFIX}_current", "-16.8"),
                state(f"sensor.{PREFIX}_remaining_charging_time", "3600"),
                state(f"binary_sensor.{PREFIX}_vehicle_running", "off"),
                state(f"binary_sensor.{PREFIX}_battery_charging", "on"),
                state(f"binary_sensor.{PREFIX}_charger_connected", "on"),
                state(
                    f"device_tracker.{PREFIX}_vehicle_position",
                    "home",
                    latitude=38.173509,
                    longitude=15.541493,
                ),
            ],
        )

        data = client.get_status()

        self.assertEqual(data.vehicle_state, "parked")
        self.assertEqual(data.charging_status, 1)
        self.assertTrue(data.plug_connected)
        self.assertEqual(data.charge_power_kw, 6.4)
        self.assertEqual(data.charge_voltage_v, 380.0)
        self.assertEqual(data.charge_current_a, -16.8)
        self.assertEqual(data.remaining_charge_min, 60)


if __name__ == "__main__":
    unittest.main()
