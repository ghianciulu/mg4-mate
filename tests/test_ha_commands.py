import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))

from ha_commands import HomeAssistantCommandClient


PREFIX = "lsjwh4097rn111393"


def state(entity_id, value, **attributes):
    return {
        "entity_id": entity_id,
        "state": value,
        "attributes": attributes,
    }


class HomeAssistantCommandClientTest(unittest.TestCase):
    def test_discovers_available_remote_controls(self):
        client = HomeAssistantCommandClient(
            ha_url="https://example.invalid",
            token="secret",
            entity_prefix=PREFIX,
            fetch_states=lambda: [
                state(f"lock.{PREFIX}_doors_lock", "locked"),
                state(
                    f"climate.{PREFIX}_vehicle_climate",
                    "off",
                    hvac_modes=["off", "auto"],
                    min_temp=17,
                    max_temp=31,
                    target_temp_step=1,
                    temperature=23,
                    current_temperature=32,
                ),
                state(f"switch.{PREFIX}_front_window_defroster_heating", "off"),
                state(f"number.{PREFIX}_target_soc", "90", min=40, max=100, step=10, unit_of_measurement="%"),
                state(f"select.{PREFIX}_charge_current_limit", "Max", options=["6A", "8A", "16A", "Max"]),
            ],
            call_service=lambda domain, service, payload: {"ok": True},
        )

        controls = client.get_controls()

        self.assertEqual(controls["locks"]["doors"]["state"], "locked")
        self.assertEqual(controls["climate"]["state"], "off")
        self.assertEqual(controls["climate"]["temperature"], 23)
        self.assertEqual(controls["climate"]["min_temp"], 17)
        self.assertEqual(controls["switches"]["front_defroster"]["state"], "off")
        self.assertEqual(controls["numbers"]["target_soc"]["max"], 100)
        self.assertEqual(controls["selects"]["charge_current_limit"]["options"], ["6A", "8A", "16A", "Max"])

    def test_calls_expected_home_assistant_services(self):
        calls = []
        client = HomeAssistantCommandClient(
            ha_url="https://example.invalid",
            token="secret",
            entity_prefix=PREFIX,
            fetch_states=lambda: [],
            call_service=lambda domain, service, payload: calls.append((domain, service, payload)) or {"ok": True},
        )

        client.lock_entity(f"lock.{PREFIX}_doors_lock")
        client.unlock_entity(f"lock.{PREFIX}_doors_lock")
        client.turn_on_switch(f"switch.{PREFIX}_charging")
        client.turn_off_switch(f"switch.{PREFIX}_charging")
        client.turn_on_climate(f"climate.{PREFIX}_vehicle_climate")
        client.turn_off_climate(f"climate.{PREFIX}_vehicle_climate")
        client.set_climate_temperature(f"climate.{PREFIX}_vehicle_climate", 22)
        client.set_number(f"number.{PREFIX}_target_soc", 80)
        client.select_option(f"select.{PREFIX}_charge_current_limit", "16A")

        self.assertEqual(calls, [
            ("lock", "lock", {"entity_id": f"lock.{PREFIX}_doors_lock"}),
            ("lock", "unlock", {"entity_id": f"lock.{PREFIX}_doors_lock"}),
            ("switch", "turn_on", {"entity_id": f"switch.{PREFIX}_charging"}),
            ("switch", "turn_off", {"entity_id": f"switch.{PREFIX}_charging"}),
            ("climate", "turn_on", {"entity_id": f"climate.{PREFIX}_vehicle_climate"}),
            ("climate", "turn_off", {"entity_id": f"climate.{PREFIX}_vehicle_climate"}),
            ("climate", "set_temperature", {"entity_id": f"climate.{PREFIX}_vehicle_climate", "temperature": 22}),
            ("number", "set_value", {"entity_id": f"number.{PREFIX}_target_soc", "value": 80}),
            ("select", "select_option", {"entity_id": f"select.{PREFIX}_charge_current_limit", "option": "16A"}),
        ])


if __name__ == "__main__":
    unittest.main()
