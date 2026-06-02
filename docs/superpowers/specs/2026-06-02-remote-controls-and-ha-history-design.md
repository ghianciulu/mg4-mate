# MG4 Mate Remote Controls and Home Assistant History Import Design

## Context

MG4 Mate currently reads MG4 data from Home Assistant entities published by the SAIC MQTT Gateway. The poller stores live snapshots in SQLite and the web UI renders overview, trips, charges, vehicle status, statistics and settings.

The next feature adds:

- A remote controls page for actions exposed by Home Assistant.
- A first-run/import workflow that can backfill MG4 Mate from Home Assistant historical states.

These are related because both use the Home Assistant REST API, but they should remain separate modules. Commands mutate vehicle state immediately; history import is a batch data process that writes local records.

## Discovered Home Assistant Capabilities

The current MG4 integration exposes these relevant entities:

- `lock.<prefix>_doors_lock`
- `lock.<prefix>_boot_lock`
- `lock.<prefix>_charging_cable_lock`
- `climate.<prefix>_vehicle_climate`
- `switch.<prefix>_front_window_defroster_heating`
- `switch.<prefix>_vehicle_climate_fan_only`
- `switch.<prefix>_rear_window_defroster_heating`
- `switch.<prefix>_battery_heating`
- `switch.<prefix>_charging`
- `switch.<prefix>_find_my_car`
- `number.<prefix>_target_soc`
- `select.<prefix>_charge_current_limit`
- `select.<prefix>_heated_seat_front_left_level`
- `select.<prefix>_heated_seat_front_right_level`
- schedule-related select/text entities for charging and battery heating.

The climate entity supports:

- `hvac_modes`: `off`, `auto`
- `min_temp`: `17`
- `max_temp`: `31`
- `target_temp_step`: `1`
- `temperature`: current target temperature
- `current_temperature`: cabin temperature

The implementation must discover availability from Home Assistant state at runtime. A missing entity should hide or disable its related command instead of causing an error.

## Remote Controls UX

Add a new sidebar item:

- Label: `Comandi` in Italian, `Controls` in English.
- Page route: `/controls`.

Use the approved "mix" layout:

- A compact cockpit-style hero at the top.
- Operational command cards below.

The page should be mobile-first because the user accesses it from the Home Assistant app.

### Hero Section

The hero summarizes:

- Door lock state.
- Climate state and target temperature.
- Cabin temperature when available.
- Home Assistant command connection status.

The cockpit visual should be decorative and compact. It must not compress or overlap controls on narrow screens. Actual command buttons live in the cards below.

### Command Sections

Security:

- Lock/unlock doors.
- Lock/unlock boot.
- Lock/unlock charging cable.

Climate:

- Turn climate on.
- Turn climate off.
- Set target temperature with minus/plus controls, clamped to the Home Assistant climate min/max.
- Toggle fan-only switch when available.
- Toggle front defroster.
- Toggle rear defroster.

Charging and Battery:

- Turn charging on/off when exposed.
- Set target SOC via number entity.
- Set charge current limit via select entity.
- Toggle battery heating.

Comfort and Utility:

- Set heated seat front-left level.
- Set heated seat front-right level.
- Trigger find-my-car if exposed.

Scheduling:

- Do not include the full scheduling editor in this implementation. Schedule controls have additional validation edge cases and are explicitly out of scope for this phase.

### Command Feedback

Each command should return visible feedback in the page:

- Success: concise green message with the action name.
- Home Assistant API error: red message with the service/entity that failed.
- Missing entity: disabled control or hidden card, not a crash.

The UI should refresh state after a command by re-reading Home Assistant state. It should not assume the command succeeded merely because the service call returned.

## Remote Controls Architecture

Add a web-layer Home Assistant command client, separate from the poller client:

- Reads `HA_URL`, `HA_TOKEN`, and `HA_ENTITY_PREFIX` from the existing SQLite settings table, environment variables, or add-on options.
- Fetches `/api/states` for current command entity states.
- Calls `/api/services/{domain}/{service}` with `{"entity_id": ...}` and any service-specific fields.

The client should expose typed methods or command descriptors for:

- `lock_entity(entity_id)`
- `unlock_entity(entity_id)`
- `turn_on_switch(entity_id)`
- `turn_off_switch(entity_id)`
- `set_climate_temperature(entity_id, temperature)`
- `turn_on_climate(entity_id)`
- `turn_off_climate(entity_id)`
- `set_number(entity_id, value)`
- `select_option(entity_id, option)`

The template should use descriptors rather than hardcoded assumptions where practical. The first version can define known MG4 suffixes in code because the SAIC MQTT Gateway uses predictable entity ids.

## Home Assistant History Import UX

Add an import panel, initially in Settings:

- Shows whether historical data has already been imported.
- Lets the user import the last 7 days by default.
- Allows 1, 7, 14 or 30 days.
- Runs as a synchronous request for this implementation, with a clear timeout/error message if Home Assistant takes too long. Background import jobs are out of scope for this phase.

The import should be safe to run more than once.

## Home Assistant History Import Data Flow

Use the Home Assistant History API:

- Endpoint: `/api/history/period/{start_time}`
- Filter entity ids to the MG4 entities needed for snapshots.
- Use `minimal_response` only if it still returns the attributes required for location; otherwise request full state data for the tracker.

Entities to import:

- SOC
- range
- mileage
- vehicle speed
- power
- voltage
- current
- remaining charging time
- interior temperature
- exterior temperature
- vehicle position tracker
- vehicle running
- battery charging
- charger connected
- doors lock
- boot
- windows

Convert historical state changes into chronological `VehicleData` snapshots:

- Build a time-ordered stream from all returned states.
- Maintain latest-known values per entity.
- Emit a snapshot when enough core fields are known: SOC, odometer, speed/running, and a timestamp.
- Include GPS only when tracker attributes include latitude and longitude.
- Skip duplicate timestamps and invalid numeric values.

Feed snapshots through the existing `Recorder.process()` so trip and charge detection remains consistent with live polling.

## Idempotency and Safety

The import must avoid duplicating positions:

- Before inserting a historical snapshot, check whether a position for the same vehicle and `recorded_at` already exists.
- If the existing schema makes exact duplicate checks awkward, add an index or helper query rather than relying on UI-side filtering.

The import must not call any Home Assistant services. It is read-only with respect to Home Assistant.

## Tests

Remote controls:

- Unit test command entity discovery from a mocked `/api/states` response.
- Unit test service payloads for lock, climate temperature, switch, number and select commands.
- Unit test unavailable/missing entities produce disabled descriptors.

History import:

- Unit test mapping Home Assistant history arrays into chronological snapshots.
- Unit test duplicate historical snapshots are skipped.
- Unit test incomplete history does not crash and only emits valid snapshots.

Regression:

- Existing `tests/test_ha_client.py` must continue passing.
- Python compile check must include new web and import modules.

## Release

After implementation:

- Bump source changelog.
- Bump add-on version.
- Pin add-on Dockerfile to the new MG4 Mate source commit.
- Verify no Home Assistant token is committed.
