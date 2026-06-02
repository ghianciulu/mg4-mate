"""Shared vehicle data model consumed by the recorder."""
from dataclasses import dataclass


@dataclass
class VehicleData:
    vin: str
    timestamp_ms: int
    soc: float
    range_km: float
    odometer_km: float
    speed_kmh: float
    gear: str
    vehicle_state: str
    charging_status: int
    charge_power_kw: float
    latitude: float
    longitude: float
    outside_temp: float
    inside_temp: float
    climate_target_temp: float
    battery_min_temp: float
    is_locked: bool
    climate_on: bool
    climate_cooling: bool
    climate_heating: bool
    climate_defrost: bool
    trunk_open: bool
    windows_open: bool
    sunshade_open: bool
    any_door_open: bool
    plug_connected: bool
    remaining_charge_min: int
    charge_voltage_v: float
    charge_current_a: float

    def fingerprint(self) -> tuple:
        """Compact snapshot of signals that indicate car activity."""
        return (
            self.is_locked,
            round(self.soc),
            round(self.inside_temp),
            self.any_door_open,
            self.charging_status,
            self.plug_connected,
        )
