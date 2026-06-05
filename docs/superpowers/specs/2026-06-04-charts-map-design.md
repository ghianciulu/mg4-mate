# Charts & Map Page — Design Spec
Date: 2026-06-04

## Scope
New `/charts` page with 4 analytical sections. Notifications (feature 1) deferred.

## Features

### 1. SOC History Chart
- ApexCharts line chart (already in base.html)
- Hourly average sampling via SQL GROUP BY hour
- Period selector: 7d / 30d / 90d / All — HTMX call to `/api/charts/soc-history?days=N`
- Color: green/yellow/red gradient matching existing SOC bar

### 2. Monthly Charge Costs
- ApexCharts stacked bar chart, one group per month, one bar per charge type (Home/AC/Fast/HPC)
- Last 12 months; tooltip shows kWh + cost per type
- Fallback message if no costs configured

### 3. Efficiency vs Outside Temperature
- ApexCharts scatter chart
- X = outside temperature at trip start (subquery on positions WHERE recorded_at <= started_at)
- Y = kWh/100km; point size proportional to distance; tooltip with date and km
- Filter: distance_km >= 2, efficiency NOT NULL, temp available
- Linear regression trend line computed in JS

### 4. All-Trips Map
- Leaflet polylines (same CDN as status_card.html)
- Each trip = polyline colored by efficiency (green=efficient, red=high consumption)
- Click polyline → popup with date, km, kWh/100km
- Limit: last 200 trips
- Auto-fit bounds; efficiency filter slider

## New sidebar entry
Icon 📈, label `nav_charts`, route `/charts`, placed between Statistics and Vehicle.

## Backend changes

### db_reader.py — 4 new functions
| Function | Tables | Returns |
|---|---|---|
| `get_soc_history(days)` | `positions` | `[{hour, avg_soc}]` |
| `get_monthly_charge_costs()` | `charges` | `[{month, charge_type, cost, kwh}]` |
| `get_efficiency_vs_temp()` | `trips` + `positions` subquery | `[{eff, temp, km, date}]` |
| `get_trip_paths(limit=200)` | `trip_positions` JOIN `trips` | `[{trip_id, eff, points:[{lat,lng}]}]` |

### web/main.py — 4 new JSON endpoints + 1 HTML route
- `GET /charts` → HTML page
- `GET /api/charts/soc-history?days=30` → JSON
- `GET /api/charts/monthly-costs` → JSON
- `GET /api/charts/efficiency-temp` → JSON
- `GET /api/charts/trip-paths?limit=200` → JSON

### i18n.py — new keys
`nav_charts`, `charts_title`, `soc_history`, `monthly_costs`, `efficiency_vs_temp`, `trip_paths`, `last_7d`, `last_30d`, `last_90d`, `no_cost_data`, `no_temp_data`

## No DB migrations needed
All required data already exists in: `positions`, `trips`, `trip_positions`, `charges`.

## Constraints
- No new Python dependencies
- Chart.js already in statistics.html; ApexCharts already in base.html — use ApexCharts for new charts
- Leaflet CDN same version as status_card.html (1.9.4)
- All HTMX paths relative (HA ingress base href constraint)
