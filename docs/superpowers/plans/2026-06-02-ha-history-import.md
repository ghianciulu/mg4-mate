# Home Assistant History Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill MG4 Mate from Home Assistant historical states so a fresh install can start with existing positions, trips and charge sessions.

**Architecture:** Add a focused `poller/ha_history.py` module that fetches Home Assistant History API data, converts entity state changes into chronological `VehicleData` snapshots, and imports those snapshots into SQLite with historical timestamps. Keep the import separate from live polling and from remote commands.

**Tech Stack:** Python 3.12, Home Assistant REST API, SQLite, existing `VehicleData` model, `unittest`, FastAPI/Jinja/HTMX for the import trigger.

---

## File Structure

- Create `poller/ha_history.py`: fetch history, map historical state arrays to snapshots, import positions/trips/charges.
- Create `tests/test_ha_history.py`: unit tests for mapping and duplicate-safe import.
- Modify `poller/db.py`: add historical insert helpers and duplicate checks.
- Modify `web/main.py`: add `/api/history-import` endpoint.
- Modify `web/templates/settings.html`: add import panel.
- Modify `CHANGELOG.md`: record history import.

## Implementation Tasks

- [ ] Add tests showing history state arrays become chronological `VehicleData` snapshots.
- [ ] Add tests showing duplicate `positions.recorded_at` rows are skipped.
- [ ] Add `Database.position_exists()` and `Database.save_position_at()`.
- [ ] Add `HomeAssistantHistoryClient.fetch_history(days)`.
- [ ] Add `history_to_snapshots()` to maintain latest-known entity values and emit valid snapshots.
- [ ] Add `HistoryImporter.import_days(days)` that writes positions and derives simple trips/charges from historical state transitions.
- [ ] Add Settings import panel with 1/7/14/30 day options and HTMX feedback.
- [ ] Add FastAPI endpoint that runs import synchronously with clamped day values.
- [ ] Verify tests, compile, token scan, and bump add-on version.

## Import Semantics

The first implementation imports:

- `positions` for every valid historical snapshot.
- `trips` by grouping contiguous driving/running/speed>1 snapshots.
- `trip_positions` for GPS points in imported trips.
- `charges` by grouping contiguous charging/plugged snapshots.

Trips shorter than 2 GPS points or below 0.2 km are ignored. Charges with no SOC gain are ignored. Import is idempotent by checking existing historical `recorded_at` values before inserting positions.

## Verification Commands

```bash
python3 -m unittest tests/test_ha_client.py tests/test_ha_commands.py tests/test_ha_history.py -v
python3 -m py_compile poller/ha_client.py poller/ha_history.py poller/vehicle_data.py poller/recorder.py poller/state_machine.py poller/main.py web/main.py web/db_reader.py web/ha_commands.py web/i18n.py
PYTHONPATH=web python3 -c 'import main; print("web import ok")'
rg -n "HA_TOKEN=|Bearer " .
```
