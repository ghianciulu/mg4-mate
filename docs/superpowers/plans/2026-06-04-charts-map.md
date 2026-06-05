# Charts & Map Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/charts` page with SOC history linechart, monthly charge costs stacked bar, efficiency vs temperature scatter, and all-trips polyline map.

**Architecture:** Four new `db_reader.py` query functions feed four JSON API endpoints in `main.py`. A single `charts.html` template renders all sections using ApexCharts (already in `base.html`) and Leaflet (same CDN as `status_card.html`). All `fetch()` calls use relative URLs — they resolve against `document.baseURI` set by `<base href>` in `base.html`, so HA ingress works without any manual URL construction.

**Tech Stack:** FastAPI, Jinja2, ApexCharts (CDN already in base.html), Leaflet 1.9.4 (CDN already in status_card.html), SQLite, pytest.

---

### Task 1: `get_soc_history()` — DB query

**Files:**
- Create: `tests/test_charts_queries.py`
- Modify: `web/db_reader.py` (append after `get_ac_dc_stats`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_charts_queries.py`:

```python
"""Tests for the four chart query functions in web/db_reader.py."""
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))


def _base_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS vehicles (id INTEGER PRIMARY KEY, vin TEXT, car_type TEXT);
        INSERT OR IGNORE INTO settings VALUES ('setup_complete', '1');
    """)


def _reset(db_reader_mod) -> None:
    for attr in ("_ro_conn", "_rw_conn"):
        conn = getattr(db_reader_mod, attr, None)
        if conn:
            try: conn.close()
            except Exception: pass
        setattr(db_reader_mod, attr, None)


class TestGetSocHistory(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        con = sqlite3.connect(self._tmp.name)
        _base_schema(con)
        con.executescript("""
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY,
                vehicle_id INTEGER,
                recorded_at TEXT,
                soc REAL
            );
            -- Two readings in the same hour → should average to 60.0
            INSERT INTO positions VALUES (1, 1, '2026-05-01 08:00:00', 50.0);
            INSERT INTO positions VALUES (2, 1, '2026-05-01 08:30:00', 70.0);
            -- One reading in a different hour
            INSERT INTO positions VALUES (3, 1, '2026-05-01 09:00:00', 80.0);
            -- NULL soc — must be excluded
            INSERT INTO positions VALUES (4, 1, '2026-05-01 10:00:00', NULL);
        """)
        con.commit()
        con.close()

        import db_reader
        db_reader.DB_PATH = self._tmp.name
        _reset(db_reader)
        self.dr = db_reader

    def tearDown(self):
        import db_reader
        _reset(db_reader)
        os.unlink(self._tmp.name)

    def test_returns_list(self):
        result = self.dr.get_soc_history(days=0)
        self.assertIsInstance(result, list)

    def test_excludes_null_soc(self):
        result = self.dr.get_soc_history(days=0)
        self.assertEqual(len(result), 2, "Expected 2 hourly buckets (NULL excluded)")

    def test_hourly_average(self):
        result = self.dr.get_soc_history(days=0)
        hours = {r["hour"]: r["avg_soc"] for r in result}
        self.assertIn("2026-05-01T08:00:00", hours)
        self.assertAlmostEqual(hours["2026-05-01T08:00:00"], 60.0, places=1)

    def test_days_filter(self):
        # days=1 means last 1 day; all rows are old, should return empty
        result = self.dr.get_soc_history(days=1)
        self.assertEqual(result, [])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/hangy/mg4-mate && python -m pytest tests/test_charts_queries.py::TestGetSocHistory -v
```

Expected: `AttributeError: module 'db_reader' has no attribute 'get_soc_history'`

- [ ] **Step 3: Implement `get_soc_history` in `web/db_reader.py`**

Append after the last function in the file:

```python
def get_soc_history(days: int = 30) -> list[dict]:
    db = _get()
    if days > 0:
        rows = db.execute(
            """SELECT
                   strftime('%Y-%m-%dT%H:00:00', recorded_at) AS hour,
                   ROUND(AVG(soc), 1) AS avg_soc
               FROM positions
               WHERE soc IS NOT NULL
                 AND recorded_at >= datetime('now', ?)
               GROUP BY hour
               ORDER BY hour ASC""",
            (f"-{days} days",),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT
                   strftime('%Y-%m-%dT%H:00:00', recorded_at) AS hour,
                   ROUND(AVG(soc), 1) AS avg_soc
               FROM positions
               WHERE soc IS NOT NULL
               GROUP BY hour
               ORDER BY hour ASC""",
        ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd /Users/hangy/mg4-mate && python -m pytest tests/test_charts_queries.py::TestGetSocHistory -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/hangy/mg4-mate && git add tests/test_charts_queries.py web/db_reader.py && git commit -m "feat: add get_soc_history query with hourly averaging"
```

---

### Task 2: `get_monthly_charge_costs()` — DB query

**Files:**
- Modify: `tests/test_charts_queries.py` (append new test class)
- Modify: `web/db_reader.py` (append)

- [ ] **Step 1: Add failing test**

Append to `tests/test_charts_queries.py`:

```python
class TestGetMonthlyChargeCosts(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        con = sqlite3.connect(self._tmp.name)
        _base_schema(con)
        con.executescript("""
            CREATE TABLE charges (
                id INTEGER PRIMARY KEY,
                vehicle_id INTEGER,
                started_at TEXT,
                ended_at TEXT,
                location_type TEXT,
                max_power_kw REAL,
                cost REAL,
                energy_added_kwh REAL
            );
            -- HOME charge in May
            INSERT INTO charges VALUES (1,1,'2026-05-10 20:00','2026-05-10 22:00','HOME',7.4,1.50,10.2);
            -- AC charge in May (no location_type → infer from max_power_kw=11)
            INSERT INTO charges VALUES (2,1,'2026-05-15 12:00','2026-05-15 13:00',NULL,11.0,2.20,15.0);
            -- HOME charge in June
            INSERT INTO charges VALUES (3,1,'2026-06-01 21:00','2026-06-01 23:00','HOME',7.4,1.80,12.0);
            -- Charge with no ended_at — must be excluded
            INSERT INTO charges VALUES (4,1,'2026-06-02 08:00',NULL,'HOME',7.4,NULL,NULL);
        """)
        con.commit()
        con.close()

        import db_reader
        db_reader.DB_PATH = self._tmp.name
        _reset(db_reader)
        self.dr = db_reader

    def tearDown(self):
        import db_reader
        _reset(db_reader)
        os.unlink(self._tmp.name)

    def test_returns_list(self):
        result = self.dr.get_monthly_charge_costs()
        self.assertIsInstance(result, list)

    def test_excludes_open_charges(self):
        result = self.dr.get_monthly_charge_costs()
        months = [r["month"] for r in result]
        # Only 2026-05 and 2026-06 should appear (charge 4 has no ended_at)
        self.assertIn("2026-05", months)
        self.assertIn("2026-06", months)

    def test_may_home_cost(self):
        result = self.dr.get_monthly_charge_costs()
        may_home = next((r for r in result if r["month"] == "2026-05" and r["charge_type"] == "HOME"), None)
        self.assertIsNotNone(may_home)
        self.assertAlmostEqual(may_home["total_cost"], 1.50, places=2)

    def test_infers_type_from_power(self):
        result = self.dr.get_monthly_charge_costs()
        may_ac = next((r for r in result if r["month"] == "2026-05" and r["charge_type"] == "AC"), None)
        self.assertIsNotNone(may_ac, "Should infer AC type from max_power_kw=11")
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/hangy/mg4-mate && python -m pytest tests/test_charts_queries.py::TestGetMonthlyChargeCosts -v
```

Expected: `AttributeError: module 'db_reader' has no attribute 'get_monthly_charge_costs'`

- [ ] **Step 3: Implement `get_monthly_charge_costs` in `web/db_reader.py`**

Append after `get_soc_history`:

```python
def get_monthly_charge_costs() -> list[dict]:
    db = _get()
    rows = db.execute(
        """SELECT
               strftime('%Y-%m', started_at) AS month,
               COALESCE(location_type,
                   CASE
                       WHEN max_power_kw <= 8  THEN 'HOME'
                       WHEN max_power_kw <= 22 THEN 'AC'
                       WHEN max_power_kw <= 80 THEN 'FAST'
                       ELSE 'HPC'
                   END
               ) AS charge_type,
               ROUND(SUM(cost), 2)            AS total_cost,
               ROUND(SUM(energy_added_kwh), 1) AS total_kwh,
               COUNT(*)                        AS session_count
           FROM charges
           WHERE ended_at IS NOT NULL
             AND started_at IS NOT NULL
           GROUP BY month, charge_type
           ORDER BY month ASC""",
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd /Users/hangy/mg4-mate && python -m pytest tests/test_charts_queries.py::TestGetMonthlyChargeCosts -v
```

- [ ] **Step 5: Commit**

```bash
cd /Users/hangy/mg4-mate && git add tests/test_charts_queries.py web/db_reader.py && git commit -m "feat: add get_monthly_charge_costs query grouped by month and type"
```

---

### Task 3: `get_efficiency_vs_temp()` — DB query

**Files:**
- Modify: `tests/test_charts_queries.py` (append)
- Modify: `web/db_reader.py` (append)

- [ ] **Step 1: Add failing test**

Append to `tests/test_charts_queries.py`:

```python
class TestGetEfficiencyVsTemp(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        con = sqlite3.connect(self._tmp.name)
        _base_schema(con)
        con.executescript("""
            CREATE TABLE trips (
                id INTEGER PRIMARY KEY,
                vehicle_id INTEGER,
                started_at TEXT,
                ended_at TEXT,
                distance_km REAL,
                efficiency_kwh_100km REAL
            );
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY,
                vehicle_id INTEGER,
                recorded_at TEXT,
                outside_temp REAL,
                soc REAL
            );
            -- Position just before trip 1
            INSERT INTO positions VALUES (1,1,'2026-05-01 08:55:00',15.0,80.0);
            -- Trip 1: starts after the position above
            INSERT INTO trips VALUES (1,1,'2026-05-01 09:00:00','2026-05-01 09:30:00',20.0,18.5);
            -- Trip 2: starts before any position → no temp
            INSERT INTO trips VALUES (2,1,'2026-01-01 08:00:00','2026-01-01 08:30:00',5.0,22.0);
            -- Trip 3: distance < 2 → must be excluded
            INSERT INTO trips VALUES (3,1,'2026-05-02 10:00:00','2026-05-02 10:05:00',1.0,15.0);
            -- Trip 4: no efficiency → must be excluded
            INSERT INTO trips VALUES (4,1,'2026-05-03 11:00:00','2026-05-03 11:30:00',15.0,NULL);
        """)
        con.commit()
        con.close()

        import db_reader
        db_reader.DB_PATH = self._tmp.name
        _reset(db_reader)
        self.dr = db_reader

    def tearDown(self):
        import db_reader
        _reset(db_reader)
        os.unlink(self._tmp.name)

    def test_returns_list(self):
        result = self.dr.get_efficiency_vs_temp()
        self.assertIsInstance(result, list)

    def test_excludes_no_temp(self):
        result = self.dr.get_efficiency_vs_temp()
        # Trip 2 has no preceding position → excluded
        ids = [r["id"] for r in result]
        self.assertNotIn(2, ids)

    def test_excludes_short_trips(self):
        result = self.dr.get_efficiency_vs_temp()
        ids = [r["id"] for r in result]
        self.assertNotIn(3, ids, "Trip with distance < 2 km must be excluded")

    def test_excludes_no_efficiency(self):
        result = self.dr.get_efficiency_vs_temp()
        ids = [r["id"] for r in result]
        self.assertNotIn(4, ids, "Trip with NULL efficiency must be excluded")

    def test_correct_temp_lookup(self):
        result = self.dr.get_efficiency_vs_temp()
        trip1 = next((r for r in result if r["id"] == 1), None)
        self.assertIsNotNone(trip1)
        self.assertAlmostEqual(trip1["outside_temp"], 15.0, places=1)
        self.assertAlmostEqual(trip1["efficiency"], 18.5, places=1)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/hangy/mg4-mate && python -m pytest tests/test_charts_queries.py::TestGetEfficiencyVsTemp -v
```

Expected: `AttributeError: module 'db_reader' has no attribute 'get_efficiency_vs_temp'`

- [ ] **Step 3: Implement `get_efficiency_vs_temp` in `web/db_reader.py`**

Append after `get_monthly_charge_costs`:

```python
def get_efficiency_vs_temp() -> list[dict]:
    db = _get()
    rows = db.execute(
        """SELECT
               t.id,
               ROUND(t.efficiency_kwh_100km, 2) AS efficiency,
               ROUND(t.distance_km, 1)           AS distance_km,
               t.started_at,
               (SELECT p.outside_temp
                FROM positions p
                WHERE p.recorded_at <= t.started_at
                  AND p.outside_temp IS NOT NULL
                ORDER BY p.recorded_at DESC LIMIT 1) AS outside_temp
           FROM trips t
           WHERE t.ended_at IS NOT NULL
             AND t.efficiency_kwh_100km IS NOT NULL
             AND t.distance_km >= 2
           ORDER BY t.started_at DESC
           LIMIT 500""",
    ).fetchall()
    return [dict(r) for r in rows if r["outside_temp"] is not None]
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd /Users/hangy/mg4-mate && python -m pytest tests/test_charts_queries.py::TestGetEfficiencyVsTemp -v
```

- [ ] **Step 5: Commit**

```bash
cd /Users/hangy/mg4-mate && git add tests/test_charts_queries.py web/db_reader.py && git commit -m "feat: add get_efficiency_vs_temp query with correlated temp lookup"
```

---

### Task 4: `get_trip_paths()` — DB query

**Files:**
- Modify: `tests/test_charts_queries.py` (append)
- Modify: `web/db_reader.py` (append)

- [ ] **Step 1: Add failing test**

Append to `tests/test_charts_queries.py`:

```python
class TestGetTripPaths(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        con = sqlite3.connect(self._tmp.name)
        _base_schema(con)
        con.executescript("""
            CREATE TABLE trips (
                id INTEGER PRIMARY KEY,
                vehicle_id INTEGER,
                started_at TEXT,
                ended_at TEXT,
                distance_km REAL,
                efficiency_kwh_100km REAL
            );
            CREATE TABLE trip_positions (
                id INTEGER PRIMARY KEY,
                trip_id INTEGER,
                latitude REAL,
                longitude REAL,
                recorded_at TEXT
            );
            -- Trip 1: 3 positions
            INSERT INTO trips VALUES (1,1,'2026-05-01 09:00','2026-05-01 09:30',20.0,18.5);
            INSERT INTO trip_positions VALUES (1,1,45.1,9.1,'2026-05-01 09:00');
            INSERT INTO trip_positions VALUES (2,1,45.2,9.2,'2026-05-01 09:15');
            INSERT INTO trip_positions VALUES (3,1,45.3,9.3,'2026-05-01 09:30');
            -- Trip 2: only 1 position (too few) → must be excluded from result
            INSERT INTO trips VALUES (2,1,'2026-05-02 10:00','2026-05-02 10:05',1.5,NULL);
            INSERT INTO trip_positions VALUES (4,2,46.0,10.0,'2026-05-02 10:00');
            -- Trip 3: no ended_at → must be excluded
            INSERT INTO trips VALUES (3,1,'2026-05-03 11:00',NULL,0.0,NULL);
            INSERT INTO trip_positions VALUES (5,3,47.0,11.0,'2026-05-03 11:00');
            INSERT INTO trip_positions VALUES (6,3,47.1,11.1,'2026-05-03 11:05');
        """)
        con.commit()
        con.close()

        import db_reader
        db_reader.DB_PATH = self._tmp.name
        _reset(db_reader)
        self.dr = db_reader

    def tearDown(self):
        import db_reader
        _reset(db_reader)
        os.unlink(self._tmp.name)

    def test_returns_list(self):
        result = self.dr.get_trip_paths()
        self.assertIsInstance(result, list)

    def test_excludes_single_position_trip(self):
        result = self.dr.get_trip_paths()
        ids = [r["trip_id"] for r in result]
        self.assertNotIn(2, ids, "Trip with only 1 position must be excluded")

    def test_excludes_open_trip(self):
        result = self.dr.get_trip_paths()
        ids = [r["trip_id"] for r in result]
        self.assertNotIn(3, ids, "Trip with no ended_at must be excluded")

    def test_trip1_has_correct_points(self):
        result = self.dr.get_trip_paths()
        trip1 = next((r for r in result if r["trip_id"] == 1), None)
        self.assertIsNotNone(trip1)
        self.assertEqual(len(trip1["points"]), 3)
        self.assertEqual(trip1["points"][0], [45.1, 9.1])
        self.assertAlmostEqual(trip1["efficiency"], 18.5, places=1)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/hangy/mg4-mate && python -m pytest tests/test_charts_queries.py::TestGetTripPaths -v
```

- [ ] **Step 3: Implement `get_trip_paths` in `web/db_reader.py`**

Append after `get_efficiency_vs_temp`:

```python
def get_trip_paths(limit: int = 200) -> list[dict]:
    db = _get()
    trips = db.execute(
        """SELECT id, efficiency_kwh_100km, started_at, distance_km
           FROM trips
           WHERE ended_at IS NOT NULL
           ORDER BY started_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    result = []
    for trip in trips:
        pts = db.execute(
            "SELECT latitude, longitude FROM trip_positions WHERE trip_id=? ORDER BY id",
            (trip["id"],),
        ).fetchall()
        if len(pts) < 2:
            continue
        result.append({
            "trip_id":    trip["id"],
            "efficiency": trip["efficiency_kwh_100km"],
            "started_at": trip["started_at"],
            "distance_km": trip["distance_km"],
            "points": [[p["latitude"], p["longitude"]] for p in pts],
        })
    return result
```

- [ ] **Step 4: Run all chart query tests — expect PASS**

```bash
cd /Users/hangy/mg4-mate && python -m pytest tests/test_charts_queries.py -v
```

Expected: all 17 tests PASS.

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
cd /Users/hangy/mg4-mate && python -m pytest -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/hangy/mg4-mate && git add tests/test_charts_queries.py web/db_reader.py && git commit -m "feat: add get_trip_paths query for all-trips map"
```

---

### Task 5: API endpoints in `web/main.py`

**Files:**
- Modify: `web/main.py`

- [ ] **Step 1: Add `JSONResponse` to the existing import**

In `web/main.py`, line 8, change:

```python
from fastapi.responses import HTMLResponse, RedirectResponse
```

to:

```python
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
```

- [ ] **Step 2: Add 5 new routes**

Append after the `boost` route at the end of `web/main.py`:

```python
# ── Charts page ───────────────────────────────────────────────────────────────

@app.get("/charts", response_class=HTMLResponse)
async def charts_page(request: Request):
    return templates.TemplateResponse(request, "charts.html", _ctx(page="charts"))


@app.get("/api/charts/soc-history")
async def api_soc_history(days: int = 30):
    return JSONResponse(db_reader.get_soc_history(days))


@app.get("/api/charts/monthly-costs")
async def api_monthly_costs():
    return JSONResponse(db_reader.get_monthly_charge_costs())


@app.get("/api/charts/efficiency-temp")
async def api_efficiency_temp():
    return JSONResponse(db_reader.get_efficiency_vs_temp())


@app.get("/api/charts/trip-paths")
async def api_trip_paths(limit: int = 200):
    return JSONResponse(db_reader.get_trip_paths(limit))
```

- [ ] **Step 3: Verify the server starts without errors**

```bash
cd /Users/hangy/mg4-mate && python -c "from web.main import app; print('OK')" 2>&1 || python -c "import sys; sys.path.insert(0,'web'); from main import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd /Users/hangy/mg4-mate && git add web/main.py && git commit -m "feat: add /charts page route and four JSON API endpoints"
```

---

### Task 6: i18n keys

**Files:**
- Modify: `web/i18n.py`

- [ ] **Step 1: Add EN keys**

In `web/i18n.py`, append to the `"en"` dict (before its closing `}`). Find the line with `"nav_settings"` and add after the settings nav block:

```python
        # Charts page
        "nav_charts":         "Charts",
        "charts_title":       "Charts & Analytics",
        "soc_history":        "SOC History",
        "monthly_costs":      "Monthly Charge Costs",
        "efficiency_vs_temp": "Efficiency vs Temperature",
        "trip_paths":         "All Trips Map",
        "last_7d":            "7d",
        "last_30d":           "30d",
        "last_90d":           "90d",
        "all_time_label":     "All",
        "no_cost_data":       "No cost data — set prices in Settings",
        "no_temp_data":       "No data — outside temperature not yet recorded",
        "temp_axis":          "Outside temp",
        "efficiency_axis":    "Efficiency",
```

- [ ] **Step 2: Add IT keys**

In `web/i18n.py`, append to the `"it"` dict (same position, after nav_settings block):

```python
        # Charts page
        "nav_charts":         "Grafici",
        "charts_title":       "Grafici & Analisi",
        "soc_history":        "SOC nel tempo",
        "monthly_costs":      "Costi ricarica mensili",
        "efficiency_vs_temp": "Efficienza vs Temperatura",
        "trip_paths":         "Mappa tutti i percorsi",
        "last_7d":            "7g",
        "last_30d":           "30g",
        "last_90d":           "90g",
        "all_time_label":     "Tutto",
        "no_cost_data":       "Nessun dato costi — imposta i prezzi nelle Impostazioni",
        "no_temp_data":       "Nessun dato — temperatura esterna non ancora registrata",
        "temp_axis":          "Temp. esterna",
        "efficiency_axis":    "Efficienza",
```

- [ ] **Step 3: Verify no syntax errors**

```bash
cd /Users/hangy/mg4-mate && python -c "import sys; sys.path.insert(0,'web'); import i18n; t=i18n.get_t('en'); print(t('nav_charts'), t('soc_history'))"
```

Expected: `Charts SOC History`

- [ ] **Step 4: Commit**

```bash
cd /Users/hangy/mg4-mate && git add web/i18n.py && git commit -m "feat: add EN/IT translation keys for charts page"
```

---

### Task 7: Sidebar nav link in `base.html`

**Files:**
- Modify: `web/templates/base.html`

- [ ] **Step 1: Add Charts nav entry**

In `web/templates/base.html`, find this block:

```html
      <a href="statistics"  class="nav-link {% if page=='statistics'  %}active{% endif %}">
        <span class="text-lg">📊</span> <span class="hidden sm:inline">{{ t('nav_statistics') }}</span>
      </a>
      <a href="vehicle"     class="nav-link {% if page=='vehicle'     %}active{% endif %}">
```

Replace with:

```html
      <a href="statistics"  class="nav-link {% if page=='statistics'  %}active{% endif %}">
        <span class="text-lg">📊</span> <span class="hidden sm:inline">{{ t('nav_statistics') }}</span>
      </a>
      <a href="charts"      class="nav-link {% if page=='charts'      %}active{% endif %}">
        <span class="text-lg">📈</span> <span class="hidden sm:inline">{{ t('nav_charts') }}</span>
      </a>
      <a href="vehicle"     class="nav-link {% if page=='vehicle'     %}active{% endif %}">
```

- [ ] **Step 2: Commit**

```bash
cd /Users/hangy/mg4-mate && git add web/templates/base.html && git commit -m "feat: add Charts entry to sidebar navigation"
```

---

### Task 8: `charts.html` template

**Files:**
- Create: `web/templates/charts.html`

- [ ] **Step 1: Create the full template**

Create `web/templates/charts.html`:

```html
{% extends "base.html" %}
{% block title %}{{ t('charts_title') }} — MG4 Mate{% endblock %}

{% block content %}
<div class="mb-6">
  <h1 class="text-2xl font-bold text-white">{{ t('charts_title') }}</h1>
</div>

<!-- SOC History -->
<div class="card mb-6">
  <div class="flex items-center justify-between mb-4">
    <div class="text-white font-semibold">🔋 {{ t('soc_history') }}</div>
    <div class="flex gap-2" id="soc-period-btns">
      {% for days, label in [(7, t('last_7d')), (30, t('last_30d')), (90, t('last_90d')), (0, t('all_time_label'))] %}
      <button onclick="loadSoc({{ days }})" id="soc-btn-{{ days }}"
              style="font-size:12px;padding:3px 12px;border-radius:9999px;border:1px solid #475569;color:#94a3b8;background:transparent;cursor:pointer;transition:all .15s"
              onmouseover="this.style.color='white'" onmouseout="if(this.id!==activeSocBtn)this.style.color='#94a3b8'">
        {{ label }}
      </button>
      {% endfor %}
    </div>
  </div>
  <div id="soc-chart" style="min-height:220px"></div>
</div>

<!-- Monthly Costs -->
<div class="card mb-6">
  <div class="text-white font-semibold mb-4">💰 {{ t('monthly_costs') }}</div>
  <div id="costs-chart" style="min-height:220px"></div>
</div>

<!-- Efficiency vs Temperature -->
<div class="card mb-6">
  <div class="text-white font-semibold mb-4">🌡️ {{ t('efficiency_vs_temp') }}</div>
  <div id="efftemp-chart" style="min-height:280px"></div>
</div>

<!-- All Trips Map -->
<div class="card">
  <div class="text-white font-semibold mb-4">🗺️ {{ t('trip_paths') }}</div>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <div id="trips-map" style="height:500px;border-radius:12px;overflow:hidden"></div>
  <div class="mt-3 flex flex-wrap gap-3 text-xs text-slate-400">
    <span><span style="color:#22c55e">■</span> &lt;18 kWh/100km</span>
    <span><span style="color:#f59e0b">■</span> 18–22 kWh/100km</span>
    <span><span style="color:#ef4444">■</span> &gt;22 kWh/100km</span>
    <span><span style="color:#64748b">■</span> {{ t('no_data') }}</span>
  </div>
</div>

<script>
let activeSocBtn = 'soc-btn-30';
let socChart;

function _setActiveSocBtn(days) {
  activeSocBtn = 'soc-btn-' + days;
  document.querySelectorAll('#soc-period-btns button').forEach(b => {
    const active = b.id === activeSocBtn;
    b.style.borderColor = active ? '#14b8a6' : '#475569';
    b.style.color       = active ? '#14b8a6' : '#94a3b8';
  });
}

async function loadSoc(days) {
  _setActiveSocBtn(days);
  const url = 'api/charts/soc-history?days=' + days;
  const data = await fetch(url).then(r => r.json());
  const series = data.map(d => [new Date(d.hour).getTime(), d.avg_soc]);

  if (!socChart) {
    socChart = new ApexCharts(document.getElementById('soc-chart'), {
      series: [{ name: 'SOC %', data: series }],
      chart: {
        type: 'area', height: 220, background: 'transparent',
        toolbar: { show: false },
        zoom: { enabled: true },
      },
      theme: { mode: 'dark' },
      dataLabels: { enabled: false },
      stroke: { curve: 'smooth', width: 2 },
      fill: {
        type: 'gradient',
        gradient: { shadeIntensity: 1, opacityFrom: 0.25, opacityTo: 0.02 },
      },
      colors: ['#14b8a6'],
      xaxis: { type: 'datetime', labels: { style: { colors: '#64748b' } } },
      yaxis: {
        min: 0, max: 100,
        labels: { formatter: v => v + '%', style: { colors: '#64748b' } },
      },
      grid: { borderColor: '#1e293b' },
      tooltip: { x: { format: 'dd MMM HH:mm' }, y: { formatter: v => v + ' %' } },
    });
    socChart.render();
  } else {
    socChart.updateSeries([{ name: 'SOC %', data: series }]);
  }
}

async function loadCosts() {
  const data = await fetch('api/charts/monthly-costs').then(r => r.json());
  const el = document.getElementById('costs-chart');
  if (!data.length) {
    el.innerHTML = '<div style="color:#64748b;text-align:center;padding:40px 0;font-size:13px">{{ t("no_cost_data") }}</div>';
    return;
  }
  const months  = [...new Set(data.map(d => d.month))].sort();
  const typeMap  = { HOME: { label: 'Home', color: '#22c55e' }, AC: { label: 'AC', color: '#60a5fa' }, FAST: { label: 'Fast DC', color: '#fb923c' }, HPC: { label: 'HPC', color: '#e879f9' } };
  const types    = Object.keys(typeMap);
  const series   = types
    .map(type => ({
      name: typeMap[type].label,
      color: typeMap[type].color,
      data: months.map(m => {
        const row = data.find(d => d.month === m && d.charge_type === type);
        return row && row.total_cost ? +row.total_cost : 0;
      }),
    }))
    .filter(s => s.data.some(v => v > 0));

  new ApexCharts(el, {
    series,
    chart: { type: 'bar', height: 220, stacked: true, background: 'transparent', toolbar: { show: false } },
    theme: { mode: 'dark' },
    colors: series.map(s => s.color),
    dataLabels: { enabled: false },
    xaxis: { categories: months, labels: { style: { colors: '#64748b' } } },
    yaxis: { labels: { formatter: v => '€' + v.toFixed(2), style: { colors: '#64748b' } } },
    grid: { borderColor: '#1e293b' },
    legend: { labels: { colors: '#94a3b8' } },
    tooltip: { y: { formatter: v => '€' + (+v).toFixed(2) } },
  }).render();
}

async function loadEffTemp() {
  const data = await fetch('api/charts/efficiency-temp').then(r => r.json());
  const el = document.getElementById('efftemp-chart');
  if (!data.length) {
    el.innerHTML = '<div style="color:#64748b;text-align:center;padding:40px 0;font-size:13px">{{ t("no_temp_data") }}</div>';
    return;
  }

  const scatter = data.map(d => ({
    x: d.outside_temp,
    y: d.efficiency,
    meta: { km: d.distance_km, date: (d.started_at || '').slice(0, 10) },
  }));

  // Linear regression trend line
  const n = data.length;
  const sumX  = data.reduce((s, d) => s + d.outside_temp, 0);
  const sumY  = data.reduce((s, d) => s + d.efficiency, 0);
  const sumXY = data.reduce((s, d) => s + d.outside_temp * d.efficiency, 0);
  const sumX2 = data.reduce((s, d) => s + d.outside_temp ** 2, 0);
  const denom = n * sumX2 - sumX ** 2;
  const slope = denom !== 0 ? (n * sumXY - sumX * sumY) / denom : 0;
  const intercept = (sumY - slope * sumX) / n;
  const xs = data.map(d => d.outside_temp);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const trend = [
    { x: xMin, y: +(slope * xMin + intercept).toFixed(2) },
    { x: xMax, y: +(slope * xMax + intercept).toFixed(2) },
  ];

  new ApexCharts(el, {
    series: [
      { name: '{{ t("efficiency_axis") }}', type: 'scatter', data: scatter },
      { name: 'Trend',                      type: 'line',    data: trend },
    ],
    chart: { height: 280, background: 'transparent', toolbar: { show: false } },
    theme: { mode: 'dark' },
    colors: ['#f59e0b', '#64748b'],
    dataLabels: { enabled: false },
    stroke: { width: [0, 2], curve: 'straight', dashArray: [0, 6] },
    markers: { size: [5, 0] },
    xaxis: {
      title: { text: '{{ t("temp_axis") }} (°C)', style: { color: '#64748b', fontSize: '11px' } },
      labels: { style: { colors: '#64748b' } },
    },
    yaxis: {
      title: { text: '{{ t("efficiency_axis") }} (kWh/100km)', style: { color: '#64748b', fontSize: '11px' } },
      labels: { style: { colors: '#64748b' } },
    },
    grid: { borderColor: '#1e293b' },
    legend: { labels: { colors: '#94a3b8' } },
    tooltip: {
      custom({ seriesIndex, dataPointIndex, w }) {
        if (seriesIndex === 1) return '';
        const d = w.config.series[0].data[dataPointIndex];
        return `<div style="background:#1e293b;padding:8px 10px;border:1px solid #334155;font-size:12px;line-height:1.6">
          <b>${d.meta.date}</b><br>${d.meta.km} km — ${d.y} kWh/100km<br>${d.x}°C</div>`;
      },
    },
  }).render();
}

async function loadMap() {
  const data = await fetch('api/charts/trip-paths').then(r => r.json());
  const container = document.getElementById('trips-map');
  if (container._leaflet_id) container._leaflet_map.remove();

  const map = L.map('trips-map');
  container._leaflet_map = map;
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap',
  }).addTo(map);

  if (!data.length) { map.setView([45, 12], 6); return; }

  const bounds = L.latLngBounds();
  data.forEach(trip => {
    if (!trip.points || trip.points.length < 2) return;
    const eff = trip.efficiency;
    const color = eff == null ? '#64748b' : eff < 18 ? '#22c55e' : eff < 22 ? '#f59e0b' : '#ef4444';
    const line = L.polyline(trip.points, { color, weight: 3, opacity: 0.7 }).addTo(map);
    const date   = (trip.started_at || '').slice(0, 10);
    const km     = trip.distance_km ? (+trip.distance_km).toFixed(1) : '?';
    const effStr = eff != null ? eff.toFixed(1) + ' kWh/100km' : '—';
    line.bindPopup(`<b>${date}</b><br>${km} km — ${effStr}`);
    trip.points.forEach(p => bounds.extend(p));
  });

  if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] });
}

// Load all sections on page load
loadSoc(30);
loadCosts();
loadEffTemp();
loadMap();
</script>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/hangy/mg4-mate && git add web/templates/charts.html && git commit -m "feat: add charts.html with SOC history, monthly costs, efficiency scatter, trip map"
```

---

### Task 9: CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update `## Unreleased`**

In `CHANGELOG.md`, replace the empty `## Unreleased` section with:

```markdown
## Unreleased

- Added Charts page (`/charts`) with four analytical sections:
  - SOC history linechart with 7d / 30d / 90d / all-time period selector.
  - Monthly charge costs stacked bar chart grouped by charge type (Home / AC / Fast / HPC).
  - Efficiency vs outside temperature scatter chart with linear regression trend line.
  - All-trips polyline map (last 200 trips), colour-coded by efficiency; click for details.
```

- [ ] **Step 2: Commit**

```bash
cd /Users/hangy/mg4-mate && git add CHANGELOG.md && git commit -m "chore: update CHANGELOG for charts page"
```

---

### Task 10: Full test suite + debug agent before push

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/hangy/mg4-mate && python -m pytest -v
```

Expected: all tests PASS (no regressions).

- [ ] **Step 2: Run systematic debug agent**

Invoke `superpowers:systematic-debugging` if any test fails. Do NOT push until all tests pass.

- [ ] **Step 3: Push**

```bash
cd /Users/hangy/mg4-mate && git push origin main
```
