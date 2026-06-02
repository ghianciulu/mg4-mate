"""Import historical MG4 states from Home Assistant history."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from db import haversine_km
from vehicle_data import VehicleData


HISTORY_SUFFIXES = {
    "sensor": [
        "soc",
        "range",
        "mileage",
        "vehicle_speed",
        "power",
        "voltage",
        "current",
        "remaining_charging_time",
        "interior_temperature",
        "exterior_temperature",
    ],
    "binary_sensor": [
        "vehicle_running",
        "battery_charging",
        "charger_connected",
        "boot",
        "window_driver",
        "window_passenger",
        "window_rear_left",
        "window_rear_right",
    ],
    "lock": ["doors_lock"],
    "device_tracker": ["vehicle_position"],
}


@dataclass
class HistoricalSnapshot:
    recorded_at: str
    data: VehicleData


class HomeAssistantHistoryClient:
    def __init__(self, ha_url: str, token: str, entity_prefix: str):
        self._ha_url = ha_url.rstrip("/")
        self._token = token
        self._entity_prefix = entity_prefix.lower()

    def entity_ids(self) -> list[str]:
        return [
            f"{domain}.{self._entity_prefix}_{suffix}"
            for domain, suffixes in HISTORY_SUFFIXES.items()
            for suffix in suffixes
        ]

    def fetch_history(self, days: int) -> list[list[dict[str, Any]]]:
        start = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 30)))
        query = urllib.parse.urlencode({
            "filter_entity_id": ",".join(self.entity_ids()),
            "minimal_response": "false",
        })
        req = urllib.request.Request(
            f"{self._ha_url}/api/history/period/{start.isoformat()}?{query}",
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))


def history_to_snapshots(history: list[list[dict[str, Any]]], entity_prefix: str) -> list[HistoricalSnapshot]:
    prefix = entity_prefix.lower()
    events: list[dict[str, Any]] = []
    for series in history:
        for item in series:
            if isinstance(item, dict) and item.get("entity_id"):
                events.append(item)
    events.sort(key=lambda item: item.get("last_updated") or item.get("last_changed") or "")

    latest: dict[str, dict[str, Any]] = {}
    snapshots: list[HistoricalSnapshot] = []
    seen: set[str] = set()
    idx = 0
    while idx < len(events):
        item = events[idx]
        ts = item.get("last_updated") or item.get("last_changed")
        if not ts:
            idx += 1
            continue
        while idx < len(events):
            grouped = events[idx]
            grouped_ts = grouped.get("last_updated") or grouped.get("last_changed")
            if grouped_ts != ts:
                break
            latest[grouped["entity_id"]] = grouped
            idx += 1
        data = _vehicle_data(latest, prefix, ts)
        if not data:
            continue
        recorded_at = _normalize_ts(ts)
        if recorded_at in seen:
            continue
        seen.add(recorded_at)
        snapshots.append(HistoricalSnapshot(recorded_at=recorded_at, data=data))
    return snapshots


class HistoryImporter:
    def __init__(self, db, vehicle_id: int, entity_prefix: str):
        self._db = db
        self._vehicle_id = vehicle_id
        self._entity_prefix = entity_prefix.lower()

    def import_history(self, history: list[list[dict[str, Any]]]) -> dict[str, int]:
        snapshots = history_to_snapshots(history, self._entity_prefix)
        inserted: list[HistoricalSnapshot] = []
        for snapshot in snapshots:
            if self._db.position_exists(self._vehicle_id, snapshot.recorded_at):
                continue
            self._db.save_position_at(self._vehicle_id, snapshot.data, snapshot.recorded_at)
            inserted.append(snapshot)
        trips = self._import_trips(inserted)
        charges = self._import_charges(inserted)
        self._db.set_setting("ha_history_last_import", datetime.now(timezone.utc).isoformat())
        return {"positions": len(inserted), "trips": trips, "charges": charges}

    def import_days(self, client: HomeAssistantHistoryClient, days: int) -> dict[str, int]:
        return self.import_history(client.fetch_history(days))

    def _import_trips(self, snapshots: list[HistoricalSnapshot]) -> int:
        imported = 0
        active: list[HistoricalSnapshot] = []
        for snapshot in snapshots + [None]:
            driving = bool(snapshot and (snapshot.data.vehicle_state == "driving" or snapshot.data.speed_kmh > 1))
            if driving:
                active.append(snapshot)
                continue
            if len(active) >= 2:
                imported += self._save_trip(active)
            active = []
        return imported

    def _save_trip(self, segment: list[HistoricalSnapshot]) -> int:
        gps = [s for s in segment if s.data.latitude and s.data.longitude]
        if len(gps) < 2:
            return 0
        distance = sum(
            haversine_km(
                gps[i].data.latitude, gps[i].data.longitude,
                gps[i + 1].data.latitude, gps[i + 1].data.longitude,
            )
            for i in range(len(gps) - 1)
        )
        if distance < 0.2:
            return 0
        start = segment[0]
        end = segment[-1]
        duration = (_dt(end.recorded_at) - _dt(start.recorded_at)).total_seconds() / 60
        energy = max((start.data.soc - end.data.soc) / 100.0 * self._db.get_battery_capacity(), 0)
        efficiency = (energy / distance * 100) if distance > 0.5 else None
        cur = self._db._conn.execute(
            """INSERT INTO trips (vehicle_id, started_at, ended_at, start_lat, start_lon,
               end_lat, end_lon, distance_km, start_soc, end_soc, start_odometer_km,
               end_odometer_km, duration_min, efficiency_kwh_100km, regen_kwh)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self._vehicle_id, start.recorded_at, end.recorded_at,
                start.data.latitude, start.data.longitude, end.data.latitude, end.data.longitude,
                round(distance, 3), start.data.soc, end.data.soc,
                start.data.odometer_km, end.data.odometer_km, round(duration, 1),
                round(efficiency, 2) if efficiency else None, 0.0,
            ),
        )
        trip_id = cur.lastrowid
        for point in gps:
            self._db._conn.execute(
                """INSERT INTO trip_positions (trip_id, recorded_at, latitude, longitude, speed_kmh, soc)
                   VALUES (?,?,?,?,?,?)""",
                (trip_id, point.recorded_at, point.data.latitude, point.data.longitude, point.data.speed_kmh, point.data.soc),
            )
        self._db._conn.commit()
        return 1

    def _import_charges(self, snapshots: list[HistoricalSnapshot]) -> int:
        imported = 0
        active: list[HistoricalSnapshot] = []
        for snapshot in snapshots + [None]:
            charging = bool(snapshot and (snapshot.data.charging_status > 0 or snapshot.data.plug_connected))
            if charging:
                active.append(snapshot)
                continue
            if len(active) >= 2:
                imported += self._save_charge(active)
            active = []
        return imported

    def _save_charge(self, segment: list[HistoricalSnapshot]) -> int:
        start = segment[0]
        end = segment[-1]
        if end.data.soc <= start.data.soc:
            return 0
        max_power = max((s.data.charge_power_kw or 0) for s in segment)
        duration = (_dt(end.recorded_at) - _dt(start.recorded_at)).total_seconds() / 60
        energy = (end.data.soc - start.data.soc) / 100.0 * self._db.get_battery_capacity()
        self._db._conn.execute(
            """INSERT INTO charges (vehicle_id, started_at, ended_at, start_soc, end_soc,
               energy_added_kwh, duration_min, latitude, longitude, charge_type, max_power_kw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self._vehicle_id, start.recorded_at, end.recorded_at,
                start.data.soc, end.data.soc, round(energy, 3), round(duration, 1),
                start.data.latitude, start.data.longitude,
                "DC" if max_power > 11 else "AC", round(max_power, 2),
            ),
        )
        self._db._conn.commit()
        return 1


def _vehicle_data(states: dict[str, dict[str, Any]], prefix: str, ts: str) -> VehicleData | None:
    soc = _float(_state(states, "sensor", prefix, "soc"))
    odometer = _float(_state(states, "sensor", prefix, "mileage"))
    speed = _float(_state(states, "sensor", prefix, "vehicle_speed"), 0.0)
    if soc is None or odometer is None:
        return None

    charging = _bool(_state(states, "binary_sensor", prefix, "battery_charging"))
    plugged = _bool(_state(states, "binary_sensor", prefix, "charger_connected"))
    running = _bool(_state(states, "binary_sensor", prefix, "vehicle_running"))
    power = abs(_float(_state(states, "sensor", prefix, "power"), 0.0) or 0.0)
    current = _float(_state(states, "sensor", prefix, "current"), 0.0) or 0.0
    voltage = _float(_state(states, "sensor", prefix, "voltage"), 0.0) or 0.0
    tracker = states.get(f"device_tracker.{prefix}_vehicle_position") or {}
    attrs = tracker.get("attributes") or {}
    vehicle_state = "driving" if running or speed > 1 else "parked"
    windows = any(_bool(_state(states, "binary_sensor", prefix, suffix)) for suffix in (
        "window_driver", "window_passenger", "window_rear_left", "window_rear_right"
    ))

    return VehicleData(
        vin=prefix.upper(),
        timestamp_ms=int(_dt(ts).timestamp() * 1000),
        soc=soc,
        range_km=_float(_state(states, "sensor", prefix, "range"), 0.0) or 0.0,
        odometer_km=odometer,
        speed_kmh=speed or 0.0,
        gear="D" if vehicle_state == "driving" else "P",
        vehicle_state=vehicle_state,
        charging_status=1 if charging else 0,
        charge_power_kw=round(power, 3),
        latitude=_float(attrs.get("latitude"), 0.0) or 0.0,
        longitude=_float(attrs.get("longitude"), 0.0) or 0.0,
        outside_temp=_float(_state(states, "sensor", prefix, "exterior_temperature"), 0.0) or 0.0,
        inside_temp=_float(_state(states, "sensor", prefix, "interior_temperature"), 0.0) or 0.0,
        climate_target_temp=0.0,
        battery_min_temp=0.0,
        is_locked=str(_state(states, "lock", prefix, "doors_lock")).lower() == "locked",
        climate_on=False,
        climate_cooling=False,
        climate_heating=False,
        climate_defrost=False,
        trunk_open=_bool(_state(states, "binary_sensor", prefix, "boot")),
        windows_open=windows,
        sunshade_open=False,
        any_door_open=False,
        plug_connected=plugged,
        remaining_charge_min=int((_float(_state(states, "sensor", prefix, "remaining_charging_time"), 0.0) or 0.0) / 60),
        charge_voltage_v=voltage,
        charge_current_a=current,
    )


def _state(states: dict[str, dict[str, Any]], domain: str, prefix: str, suffix: str) -> Any:
    return (states.get(f"{domain}.{prefix}_{suffix}") or {}).get("state")


def _bool(value: Any) -> bool:
    return str(value).lower() in {"on", "true", "1", "locked"}


def _float(value: Any, default: float | None = None) -> float | None:
    if value in (None, "", "unknown", "unavailable"):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _normalize_ts(value: str) -> str:
    return _dt(value).isoformat()
