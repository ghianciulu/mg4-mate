"""Home Assistant command client for MG4 remote controls."""
from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from typing import Any

StateFetcher = Callable[[], list[dict[str, Any]]]
ServiceCaller = Callable[[str, str, dict[str, Any]], Any]


class HomeAssistantCommandClient:
    def __init__(
        self,
        ha_url: str,
        token: str,
        entity_prefix: str,
        *,
        fetch_states: StateFetcher | None = None,
        call_service: ServiceCaller | None = None,
    ):
        self._ha_url = ha_url.rstrip("/")
        self._token = token
        self._entity_prefix = entity_prefix.lower()
        self._fetch_states = fetch_states or self._fetch_states_from_api
        self._service_caller = call_service or self._call_service_api

    def get_controls(self) -> dict[str, Any]:
        states = self._state_map(self._fetch_states())
        return {
            "online": True,
            "locks": {
                "doors": self._entity_descriptor(states, "lock", "doors_lock"),
                "boot": self._entity_descriptor(states, "lock", "boot_lock"),
                "cable": self._entity_descriptor(states, "lock", "charging_cable_lock"),
            },
            "climate": self._climate_descriptor(states),
            "switches": {
                "front_defroster": self._entity_descriptor(states, "switch", "front_window_defroster_heating"),
                "rear_defroster": self._entity_descriptor(states, "switch", "rear_window_defroster_heating"),
                "fan_only": self._entity_descriptor(states, "switch", "vehicle_climate_fan_only"),
                "battery_heating": self._entity_descriptor(states, "switch", "battery_heating"),
                "charging": self._entity_descriptor(states, "switch", "charging"),
                "find_my_car": self._entity_descriptor(states, "switch", "find_my_car"),
            },
            "numbers": {
                "target_soc": self._number_descriptor(states, "target_soc"),
            },
            "selects": {
                "charge_current_limit": self._select_descriptor(states, "charge_current_limit"),
                "heated_seat_left": self._select_descriptor(states, "heated_seat_front_left_level"),
                "heated_seat_right": self._select_descriptor(states, "heated_seat_front_right_level"),
            },
        }

    def lock_entity(self, entity_id: str) -> Any:
        return self._call_service("lock", "lock", {"entity_id": entity_id})

    def unlock_entity(self, entity_id: str) -> Any:
        return self._call_service("lock", "unlock", {"entity_id": entity_id})

    def turn_on_switch(self, entity_id: str) -> Any:
        return self._call_service("switch", "turn_on", {"entity_id": entity_id})

    def turn_off_switch(self, entity_id: str) -> Any:
        return self._call_service("switch", "turn_off", {"entity_id": entity_id})

    def turn_on_climate(self, entity_id: str) -> Any:
        return self._call_service("climate", "turn_on", {"entity_id": entity_id})

    def turn_off_climate(self, entity_id: str) -> Any:
        return self._call_service("climate", "turn_off", {"entity_id": entity_id})

    def set_climate_temperature(self, entity_id: str, temperature: float) -> Any:
        return self._call_service(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": temperature},
        )

    def set_number(self, entity_id: str, value: float) -> Any:
        return self._call_service("number", "set_value", {"entity_id": entity_id, "value": value})

    def select_option(self, entity_id: str, option: str) -> Any:
        return self._call_service(
            "select",
            "select_option",
            {"entity_id": entity_id, "option": option},
        )

    def _call_service(self, domain: str, service: str, payload: dict[str, Any]) -> Any:
        entity_id = str(payload.get("entity_id", ""))
        if not entity_id.startswith(f"{domain}.{self._entity_prefix}_"):
            raise ValueError("entity_id does not belong to this MG4")
        return self._service_caller(domain, service, payload)

    def _entity(self, domain: str, suffix: str) -> str:
        return f"{domain}.{self._entity_prefix}_{suffix}"

    def _state_map(self, states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {
            s["entity_id"]: s
            for s in states
            if isinstance(s, dict)
            and isinstance(s.get("entity_id"), str)
            and s["entity_id"].split(".", 1)[-1].startswith(self._entity_prefix)
        }

    def _entity_descriptor(self, states: dict[str, dict[str, Any]], domain: str, suffix: str) -> dict[str, Any] | None:
        entity_id = self._entity(domain, suffix)
        item = states.get(entity_id)
        if not item:
            return None
        return {
            "entity_id": entity_id,
            "state": item.get("state", "unknown"),
            "available": item.get("state") not in {"unavailable", "unknown"},
            "friendly_name": (item.get("attributes") or {}).get("friendly_name", entity_id),
        }

    def _number_descriptor(self, states: dict[str, dict[str, Any]], suffix: str) -> dict[str, Any] | None:
        base = self._entity_descriptor(states, "number", suffix)
        if not base:
            return None
        attrs = states[base["entity_id"]].get("attributes") or {}
        base.update({
            "value": self._float(states[base["entity_id"]].get("state")),
            "min": self._float(attrs.get("min"), 0),
            "max": self._float(attrs.get("max"), 100),
            "step": self._float(attrs.get("step"), 1),
            "unit": attrs.get("unit_of_measurement", ""),
        })
        return base

    def _select_descriptor(self, states: dict[str, dict[str, Any]], suffix: str) -> dict[str, Any] | None:
        base = self._entity_descriptor(states, "select", suffix)
        if not base:
            return None
        attrs = states[base["entity_id"]].get("attributes") or {}
        base["options"] = attrs.get("options") or []
        return base

    def _climate_descriptor(self, states: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        base = self._entity_descriptor(states, "climate", "vehicle_climate")
        if not base:
            return None
        attrs = states[base["entity_id"]].get("attributes") or {}
        base.update({
            "temperature": self._float(attrs.get("temperature"), 21),
            "current_temperature": self._float(attrs.get("current_temperature")),
            "min_temp": self._float(attrs.get("min_temp"), 17),
            "max_temp": self._float(attrs.get("max_temp"), 31),
            "step": self._float(attrs.get("target_temp_step"), 1),
            "hvac_modes": attrs.get("hvac_modes") or [],
        })
        return base

    def _fetch_states_from_api(self) -> list[dict[str, Any]]:
        req = urllib.request.Request(
            f"{self._ha_url}/api/states",
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def _call_service_api(self, domain: str, service: str, payload: dict[str, Any]) -> Any:
        req = urllib.request.Request(
            f"{self._ha_url}/api/services/{domain}/{service}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body else {}

    @staticmethod
    def _float(value: Any, default: float | None = None) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
