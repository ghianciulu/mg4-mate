"""Home Assistant vehicle data source for MG/SAIC MQTT entities."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from vehicle_data import VehicleData

log = logging.getLogger(__name__)

StateFetcher = Callable[[], list[dict[str, Any]]]


@dataclass
class HomeAssistantVehicle:
    vin: str
    car_type: str = "MG4"
    year: int | None = None


class HomeAssistantMateClient:
    """Read MG4 states from Home Assistant and expose the MG4 Mate data shape."""

    def __init__(
        self,
        ha_url: str,
        token: str,
        entity_prefix: str,
        *,
        fetch_states: StateFetcher | None = None,
    ):
        self._ha_url = ha_url.rstrip("/")
        self._token = token
        self._entity_prefix = entity_prefix.lower()
        self._fetch_states = fetch_states or self._fetch_states_from_api
        self._vehicle = HomeAssistantVehicle(vin=self._entity_prefix.upper())
        self.battery_capacity_kwh: float | None = None

    def login(self):
        """Validate that Home Assistant is reachable and cache static vehicle data."""
        states = self._state_map(self._fetch_states())
        self.battery_capacity_kwh = self._float(
            states, "sensor", "total_battery_capacity", default=None
        )
        log.info("Home Assistant source ready — VIN: %s model: MG4", self._vehicle.vin)

    def get_status(self) -> VehicleData:
        states = self._state_map(self._fetch_states())

        speed = self._float(states, "sensor", "vehicle_speed")
        running = self._bool(states, "binary_sensor", "vehicle_running")
        charging = self._bool(states, "binary_sensor", "battery_charging")
        plugged = self._bool(states, "binary_sensor", "charger_connected")
        power_kw = abs(self._float(states, "sensor", "power"))
        current_a = self._float(states, "sensor", "current")
        voltage_v = self._float(states, "sensor", "voltage")

        position = states.get(f"device_tracker.{self._entity_prefix}_vehicle_position", {})
        attrs = position.get("attributes") or {}
        vehicle_state = "driving" if running or speed > 1 else "parked"

        return VehicleData(
            vin=self._vehicle.vin,
            timestamp_ms=self._timestamp_ms(states),
            soc=self._float(states, "sensor", "soc"),
            range_km=self._float(states, "sensor", "range"),
            odometer_km=self._float(states, "sensor", "mileage"),
            speed_kmh=speed,
            gear="D" if vehicle_state == "driving" else "P",
            vehicle_state=vehicle_state,
            charging_status=1 if charging else 0,
            charge_power_kw=round(power_kw, 3),
            latitude=self._attr_float(attrs, "latitude"),
            longitude=self._attr_float(attrs, "longitude"),
            outside_temp=self._float(states, "sensor", "exterior_temperature"),
            inside_temp=self._float(states, "sensor", "interior_temperature"),
            climate_target_temp=0.0,
            battery_min_temp=0.0,
            is_locked=self._locked(states),
            climate_on=self._climate_on(states),
            climate_cooling=False,
            climate_heating=False,
            climate_defrost=False,
            trunk_open=self._bool(states, "binary_sensor", "boot"),
            windows_open=any(
                self._bool(states, "binary_sensor", suffix)
                for suffix in ("window_driver", "window_passenger", "window_rear_left", "window_rear_right")
            ),
            sunshade_open=False,
            any_door_open=any(
                self._bool(states, "binary_sensor", suffix)
                for suffix in ("door_driver", "door_passenger", "door_rear_left", "door_rear_right", "boot")
            ),
            plug_connected=plugged,
            remaining_charge_min=self._remaining_charge_min(states),
            charge_voltage_v=voltage_v,
            charge_current_a=current_a,
            door_fl_open=self._bool(states, "binary_sensor", "door_driver"),
            door_fr_open=self._bool(states, "binary_sensor", "door_passenger"),
            door_rl_open=self._bool(states, "binary_sensor", "door_rear_left"),
            door_rr_open=self._bool(states, "binary_sensor", "door_rear_right"),
            bonnet_open=self._bool(states, "binary_sensor", "bonnet"),
            aux_battery_v=self._float(states, "sensor", "auxiliary_battery_voltage") or 0.0,
            lights_dipped=self._bool(states, "binary_sensor", "lights_dipped_beam"),
            lights_main=self._bool(states, "binary_sensor", "lights_main_beam"),
            lights_side=self._bool(states, "binary_sensor", "lights_side"),
            heading_deg=self._float(states, "sensor", "heading") or 0.0,
            tyre_fl_bar=self._float(states, "sensor", "tyres_front_left_pressure") or 0.0,
            tyre_fr_bar=self._float(states, "sensor", "tyres_front_right_pressure") or 0.0,
            tyre_rl_bar=self._float(states, "sensor", "tyres_rear_left_pressure") or 0.0,
            tyre_rr_bar=self._float(states, "sensor", "tyres_rear_right_pressure") or 0.0,
        )

    def close(self):
        pass

    def _fetch_states_from_api(self) -> list[dict[str, Any]]:
        if not self._ha_url or not self._token:
            raise RuntimeError("HA_URL and HA_TOKEN are required for Home Assistant source")

        p = self._entity_prefix
        entity_ids = [
            f"sensor.{p}_soc",
            f"sensor.{p}_range",
            f"sensor.{p}_mileage",
            f"sensor.{p}_vehicle_speed",
            f"sensor.{p}_power",
            f"sensor.{p}_current",
            f"sensor.{p}_voltage",
            f"sensor.{p}_exterior_temperature",
            f"sensor.{p}_interior_temperature",
            f"sensor.{p}_total_battery_capacity",
            f"sensor.{p}_remaining_charging_time",
            f"sensor.{p}_remote_climate_state",
            f"binary_sensor.{p}_vehicle_running",
            f"binary_sensor.{p}_battery_charging",
            f"binary_sensor.{p}_charger_connected",
            f"binary_sensor.{p}_boot",
            f"binary_sensor.{p}_window_driver",
            f"binary_sensor.{p}_window_passenger",
            f"binary_sensor.{p}_window_rear_left",
            f"binary_sensor.{p}_window_rear_right",
            f"binary_sensor.{p}_door_driver",
            f"binary_sensor.{p}_door_passenger",
            f"binary_sensor.{p}_door_rear_left",
            f"binary_sensor.{p}_door_rear_right",
            f"binary_sensor.{p}_bonnet",
            f"sensor.{p}_auxiliary_battery_voltage",
            f"binary_sensor.{p}_lights_dipped_beam",
            f"binary_sensor.{p}_lights_main_beam",
            f"binary_sensor.{p}_lights_side",
            f"sensor.{p}_heading",
            f"sensor.{p}_tyres_front_left_pressure",
            f"sensor.{p}_tyres_front_right_pressure",
            f"sensor.{p}_tyres_rear_left_pressure",
            f"sensor.{p}_tyres_rear_right_pressure",
            f"lock.{p}_doors_lock",
            f"climate.{p}_vehicle_climate",
            f"device_tracker.{p}_vehicle_position",
        ]

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        def fetch_one(entity_id: str) -> dict[str, Any]:
            req = urllib.request.Request(
                f"{self._ha_url}/api/states/{entity_id}",
                headers=headers,
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as response:
                    body = response.read().decode("utf-8")
                return json.loads(body)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return {"entity_id": entity_id, "state": "unavailable", "attributes": {}}
                raise

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(fetch_one, entity_ids))

        return results

    def _state_map(self, states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        prefix = self._entity_prefix
        return {
            s["entity_id"]: s
            for s in states
            if isinstance(s, dict)
            and isinstance(s.get("entity_id"), str)
            and s["entity_id"].split(".", 1)[-1].startswith(prefix)
        }

    def _entity(self, domain: str, suffix: str) -> str:
        return f"{domain}.{self._entity_prefix}_{suffix}"

    def _raw_state(self, states: dict[str, dict[str, Any]], domain: str, suffix: str) -> Any:
        return (states.get(self._entity(domain, suffix)) or {}).get("state")

    def _float(
        self,
        states: dict[str, dict[str, Any]],
        domain: str,
        suffix: str,
        *,
        default: float | None = 0.0,
    ) -> float | None:
        value = self._raw_state(states, domain, suffix)
        if value in (None, "", "unknown", "unavailable"):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _bool(self, states: dict[str, dict[str, Any]], domain: str, suffix: str) -> bool:
        return str(self._raw_state(states, domain, suffix)).lower() in {"on", "true", "1", "locked"}

    def _locked(self, states: dict[str, dict[str, Any]]) -> bool:
        return str(self._raw_state(states, "lock", "doors_lock")).lower() == "locked"

    def _climate_on(self, states: dict[str, dict[str, Any]]) -> bool:
        climate = str(self._raw_state(states, "climate", "vehicle_climate")).lower()
        remote = str(self._raw_state(states, "sensor", "remote_climate_state")).lower()
        return climate not in {"", "none", "off", "unknown", "unavailable"} or remote not in {
            "",
            "none",
            "off",
            "unknown",
            "unavailable",
        }

    def _remaining_charge_min(self, states: dict[str, dict[str, Any]]) -> int:
        seconds = self._float(states, "sensor", "remaining_charging_time")
        return int((seconds or 0) / 60)

    def _timestamp_ms(self, states: dict[str, dict[str, Any]]) -> int:
        newest = max((s.get("last_updated") or "" for s in states.values()), default="")
        if newest:
            try:
                from datetime import datetime

                return int(datetime.fromisoformat(newest.replace("Z", "+00:00")).timestamp() * 1000)
            except ValueError:
                pass
        return int(time.time() * 1000)

    @staticmethod
    def _attr_float(attrs: dict[str, Any], key: str) -> float:
        value = attrs.get(key)
        try:
            return float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0
