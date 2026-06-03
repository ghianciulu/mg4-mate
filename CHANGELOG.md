# Changelog

## Unreleased

## 1.3.2

- Replaced battery temperature with outside temperature on overview status card; AC target temperature kept.

## 1.3.1

- Expanded vehicle page: individual door states, bonnet, 12V aux battery, lights on/off, compass heading — fetched from HA and stored in positions table.
- Added tyre pressure sensors (FL/FR/RL/RR) with SVG top-down car visualization; wheels colour-coded green/amber/red by pressure; low-pressure warning banner.

## 1.3.0

- Auto-correct charge start SOC: when poller wakes up during an active charge (PARKED_SLEEP gap), use the last pre-plug-in position SOC instead of the current (already-charging) SOC.
- Added manual charge edit: each charge card now has an inline edit panel to correct start/end times and SOC values; derived fields (duration, energy, cost) are recalculated automatically.

## 1.2.4

- Fixed trip merge root cause: HA ingress sets <base href> so absolute hx-post paths resolved to HA root instead of addon. Changed to relative path and added x-ingress-path prefix to HX-Redirect.

## 1.2.3

- Fixed trip merge: stale WAL read caused merged trips to appear unchanged after redirect.
- Fixed trip merge: added hx-swap="none" to merge forms to prevent HTMX swap interference.
- Added 9 unit tests covering merge correctness and WAL cache invalidation.

## 1.2.2

- Fixed trip merge button: replaced script redirect with HX-Redirect header, onsubmit with hx-confirm, and relative URL with absolute path.

## 1.2.1

- Fixed 500 error on trips page caused by `get_trips_grouped()` converting days dict to list after SQL rewrite.
- Added regression test for trips grouped structure.

## 1.2.0

- Added auto-merge for trips separated by a short gap (configurable, default 5 min).
- Added manual merge button on trip detail page to combine adjacent trips.
- Added IT/EN translations for all new merge UI strings.

## 1.1.2

- Fixed `urllib.error` import missing in HA client (would crash poller on 404).
- Fixed regen energy accumulation to use real elapsed time between polls instead of hardcoded 10 s.
- Removed dead `_conn()` function from web DB layer.
- Live map on overview now refreshes every 30 s together with the status card via HTMX.
- Optimised trip tree query: aggregation moved to SQLite, reducing Python memory use.

## 1.1.1

- Persistent SQLite connections in web layer (no more per-request `connect()`).
- Distance-weighted average efficiency in statistics summary.
- Targeted Home Assistant entity fetch: 27 individual calls in parallel instead of loading all states.
- Raised charge history default limit from 50 to 500.

## 1.1.0

- Removed broken car-picture card from overview; map now spans full width.
- Fixed HA history import to use proper DB methods instead of direct SQLite access.
- Improved mobile layout across trips, charges, statistics and trip detail pages.
- Added GitHub Actions CI (pytest on every push/PR) and release workflow (auto-updates addon on tag).

## 1.0.0

- Initial MG4 Mate release.
- Added Home Assistant REST API source for SAIC MQTT Gateway entities.
- Added local SQLite recording for MG4 positions, trips and charge sessions.
- Added web UI for overview, trips, charges, vehicle status, settings and statistics.
- Added Home Assistant-backed MG4 remote controls page.
- Added controls for locks, climate, defrosters, charging, target SOC, current limit, heated seats and find-my-car.
- Added Home Assistant history import for existing MG4 positions, trips and charge sessions.
