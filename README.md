# MG4 Mate

Trip tracking, charge logging and statistics for MG4 vehicles using Home Assistant entities from the SAIC MQTT Gateway.

MG4 Mate is a self-hosted companion inspired by TeslaMate-style trip and charge tracking. It stores data locally in SQLite and provides a web UI for overview, trips, charges, vehicle status and statistics.

## Features

- **Overview**: live SOC, range, odometer, charging state and vehicle position.
- **Trips**: automatic trip detection with route map, distance, duration and efficiency.
- **Charges**: charge sessions with SOC delta, estimated energy added, peak power and cost categories.
- **Statistics**: distance, energy use, efficiency, driving time and regeneration summaries.
- **Home Assistant source**: reads MG4 entities already published by SAIC MQTT Gateway.
- **Local storage**: data is stored in a local SQLite database.

## How It Works

```text
SAIC MQTT Gateway -> Home Assistant entities -> MG4 Mate poller -> SQLite -> Web UI
```

MG4 Mate does not call the MG/iSMART cloud directly. It reads Home Assistant state data through the Home Assistant REST API.

## Requirements

1. Home Assistant.
2. SAIC MQTT Gateway configured and publishing MG4 entities through MQTT discovery.
3. A Home Assistant long-lived access token.
4. The MG4 entity prefix, usually the lower-case VIN used in entity ids.

Example entity:

```text
sensor.lsjwh4097rnxxxxxx_soc
```

Entity prefix:

```text
lsjwh4097rnxxxxxx
```

## Home Assistant Add-On Installation

1. In Home Assistant go to **Settings -> Add-ons -> Add-on Store**.
2. Open **Repositories** from the top-right menu.
3. Add:

   ```text
   https://github.com/ghianciulu/mg4-mate-addon
   ```

4. Install **MG4 Mate**.
5. Configure the add-on options.

Recommended local configuration:

```yaml
VEHICLE_SOURCE: homeassistant
HA_URL: http://192.168.x.x:8123
HA_TOKEN: your_home_assistant_long_lived_access_token
HA_ENTITY_PREFIX: your_lowercase_vin_prefix
```

Prefer a local Home Assistant URL when possible. It avoids public DNS and HTTPS endpoint issues.

## Standalone Docker

```bash
git clone https://github.com/ghianciulu/mg4-mate.git
cd mg4-mate
docker compose up -d
```

Set these environment variables in `docker-compose.yml` or your container runtime:

```text
VEHICLE_SOURCE=homeassistant
HA_URL=http://192.168.x.x:8123
HA_TOKEN=your_home_assistant_long_lived_access_token
HA_ENTITY_PREFIX=your_lowercase_vin_prefix
```

## Expected Entities

The adapter reads these Home Assistant entities when available:

```text
sensor.<prefix>_soc
sensor.<prefix>_soc_kwh
sensor.<prefix>_range
sensor.<prefix>_mileage
sensor.<prefix>_vehicle_speed
sensor.<prefix>_power
sensor.<prefix>_voltage
sensor.<prefix>_current
sensor.<prefix>_remaining_charging_time
sensor.<prefix>_total_battery_capacity
sensor.<prefix>_interior_temperature
sensor.<prefix>_exterior_temperature
device_tracker.<prefix>_vehicle_position
binary_sensor.<prefix>_vehicle_running
binary_sensor.<prefix>_battery_charging
binary_sensor.<prefix>_charger_connected
binary_sensor.<prefix>_boot
binary_sensor.<prefix>_window_driver
binary_sensor.<prefix>_window_passenger
binary_sensor.<prefix>_window_rear_left
binary_sensor.<prefix>_window_rear_right
lock.<prefix>_doors_lock
```

## Notes

- Trip quality depends on the SAIC MQTT Gateway refresh cadence.
- Around 30-40 second updates while driving are enough for useful route maps and consumption statistics.
- Do not commit Home Assistant tokens. Pass them only through add-on options or environment variables.

## License

[GNU AGPL-3.0](./LICENSE)
