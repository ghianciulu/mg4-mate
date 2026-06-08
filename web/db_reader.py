"""Read-only DB queries for the web layer."""
import sqlite3
import time
import math
from datetime import datetime, timedelta, timezone
from typing import Optional
import os

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:
    ZoneInfo = None  # type: ignore[assignment,misc]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment,misc]


def _display_tz():
    """Return ZoneInfo for the HA-configured timezone, or None to fall back to system local."""
    try:
        tz_name = get_setting("display_timezone")
        if tz_name and ZoneInfo:
            return ZoneInfo(tz_name)
    except Exception:
        pass
    return None


def _parse_local(ts: str) -> datetime:
    """Parse a UTC ISO timestamp and return a local-time datetime."""
    dt = datetime.fromisoformat(ts.replace(" ", "T").replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    tz = _display_tz()
    return dt.astimezone(tz) if tz else dt.astimezone()


CHARGE_TYPES = {
    "HOME": {"label": "Home",       "icon": "🏠", "color": "#22c55e"},
    "AC":   {"label": "AC Public",  "icon": "🔌", "color": "#60a5fa"},
    "FAST": {"label": "Fast DC",    "icon": "⚡", "color": "#fb923c"},
    "HPC":  {"label": "HPC",        "icon": "🚀", "color": "#e879f9"},
}

PRICE_KEYS = {
    "HOME": "price_home_kwh",
    "AC":   "price_ac_kwh",
    "FAST": "price_fast_kwh",
    "HPC":  "price_hpc_kwh",
}

def auto_location_type(max_power_kw: float) -> str:
    p = max_power_kw or 0
    if p <= 8:   return "HOME"
    if p <= 22:  return "AC"
    if p <= 80:  return "FAST"
    return "HPC"


DB_PATH = os.environ.get("DB_PATH", "mg4_mate.db")

_ro_conn: sqlite3.Connection | None = None
_rw_conn: sqlite3.Connection | None = None


def _get() -> sqlite3.Connection:
    global _ro_conn
    if _ro_conn is None:
        _ro_conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
        _ro_conn.row_factory = sqlite3.Row
    return _ro_conn


def _conn_rw() -> sqlite3.Connection:
    global _rw_conn
    if _rw_conn is None:
        _rw_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _rw_conn.row_factory = sqlite3.Row
    return _rw_conn


def get_setting(key: str, default: str = "") -> str:
    db = _get()
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    db = _conn_rw()
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))
    db.commit()


def is_setup_complete() -> bool:
    return get_setting("setup_complete") == "1"


def set_sunshade_state(open: int) -> None:
    """Persist the sunshade state from the last command (signal 1724 is unreliable for shade)."""
    set_setting("sunshade_last_state", str(open))


def get_language() -> str:
    return get_setting("language", "en")


def get_charge_prices() -> dict:
    db = _get()
    rows = db.execute(
        "SELECT key, value FROM settings WHERE key LIKE 'price_%_kwh'"
    ).fetchall()
    return {r["key"]: float(r["value"]) for r in rows}


def update_charge_type(charge_id: int, location_type: str) -> dict:
    """Set location_type and recalculate cost. Returns updated charge dict."""
    db = _conn_rw()
    prices = get_charge_prices()
    price_key = PRICE_KEYS.get(location_type)
    price = prices.get(price_key, 0.0) if price_key else 0.0

    charge = db.execute("SELECT * FROM charges WHERE id=?", (charge_id,)).fetchone()
    if not charge:
        return {}

    energy = charge["energy_added_kwh"] or 0
    cost   = round(energy * price, 2) if price else None

    db.execute(
        "UPDATE charges SET location_type=?, cost=? WHERE id=?",
        (location_type, cost, charge_id)
    )
    db.commit()
    return dict(db.execute("SELECT * FROM charges WHERE id=?", (charge_id,)).fetchone())


def update_charge(charge_id: int, started_at: str, ended_at: str | None,
                  start_soc: float, end_soc: float | None) -> dict | None:
    db = _conn_rw()
    charge = db.execute("SELECT * FROM charges WHERE id=?", (charge_id,)).fetchone()
    if not charge:
        return None

    cap_row = db.execute("SELECT value FROM settings WHERE key='battery_capacity_kwh'").fetchone()
    capacity = float(cap_row["value"]) if cap_row else 64.0

    duration_min     = charge["duration_min"]
    energy_added_kwh = charge["energy_added_kwh"]
    cost             = charge["cost"]

    if ended_at and end_soc is not None:
        try:
            t0 = datetime.fromisoformat(started_at)
            t1 = datetime.fromisoformat(ended_at)
            duration_min = round(abs((t1 - t0).total_seconds()) / 60, 1)
        except Exception:
            pass
        energy_added_kwh = round(max((end_soc - start_soc) / 100.0 * capacity, 0), 3)
        location_type = charge["location_type"]
        prices   = get_charge_prices()
        price_key = PRICE_KEYS.get(location_type) if location_type else None
        price     = prices.get(price_key, 0.0) if price_key else 0.0
        cost      = round(energy_added_kwh * price, 2) if price else None

    db.execute(
        """UPDATE charges SET started_at=?, ended_at=?, start_soc=?, end_soc=?,
           energy_added_kwh=?, duration_min=?, cost=? WHERE id=?""",
        (started_at, ended_at, start_soc, end_soc, energy_added_kwh, duration_min, cost, charge_id)
    )
    db.commit()
    global _ro_conn
    _ro_conn = None
    return dict(db.execute("SELECT * FROM charges WHERE id=?", (charge_id,)).fetchone())


def update_charge_price(key: str, value: float) -> None:
    db = _conn_rw()
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))
    # Recalculate costs for all charges with a location_type
    for ctype, pkey in PRICE_KEYS.items():
        if pkey == key:
            charges = db.execute(
                "SELECT id, energy_added_kwh FROM charges WHERE location_type=?", (ctype,)
            ).fetchall()
            for c in charges:
                cost = round((c["energy_added_kwh"] or 0) * value, 2)
                db.execute("UPDATE charges SET cost=? WHERE id=?", (cost, c["id"]))
    db.commit()


def upsert_vehicle(vin: str, car_type: str) -> None:
    """Pre-populate vehicles table before the first poller run."""
    db = _conn_rw()
    db.execute(
        "INSERT OR IGNORE INTO vehicles (vin, car_type) VALUES (?,?)",
        (vin, car_type),
    )
    db.execute("UPDATE vehicles SET car_type=? WHERE vin=?", (car_type, vin))
    db.commit()


def get_vehicle():
    db = _get()
    v = db.execute("SELECT * FROM vehicles LIMIT 1").fetchone()
    s = {r["key"]: r["value"] for r in db.execute("SELECT * FROM settings").fetchall()}
    return dict(v) if v else None, s


def get_latest_status() -> Optional[dict]:
    db = _get()
    row = db.execute(
        "SELECT * FROM positions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    # Charge power: positions stores current/voltage, not a power column. Compute it
    # (|I×V|), only when the charge current is meaningful (>=3A).
    cur_a = d.get("charge_current_a")
    volt_v = d.get("charge_voltage_v")
    if cur_a is not None and volt_v is not None and abs(cur_a) >= 3.0:
        d["charge_power_kw"] = round(abs(cur_a * volt_v) / 1000.0, 2)
    else:
        d["charge_power_kw"] = 0.0
    # How long ago
    try:
        ts = datetime.fromisoformat(d["recorded_at"])
        now = datetime.now(timezone.utc)
        delta = int((now - ts).total_seconds())
        if delta < 60:
            d["last_seen"] = f"{delta}s ago"
        elif delta < 3600:
            d["last_seen"] = f"{delta // 60}m ago"
        else:
            d["last_seen"] = f"{delta // 3600}h ago"
    except Exception:
        d["last_seen"] = "unknown"
    return d


def get_trips(limit: int = 500) -> list[dict]:
    db = _get()
    rows = db.execute(
        """SELECT * FROM trips
           WHERE ended_at IS NOT NULL AND COALESCE(distance_km, 0) >= 0.1
           ORDER BY started_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_trips_grouped() -> list[dict]:
    """Return trips nested as year → month → day for the sidebar tree view."""
    from collections import OrderedDict
    db = _get()

    # Aggregate counts/km/efficiency per day in SQL
    agg_rows = db.execute("""
        SELECT
            strftime('%Y', started_at, 'localtime')       AS yr,
            strftime('%Y-%m', started_at, 'localtime')    AS mo_key,
            date(started_at, 'localtime')                 AS day_key,
            COUNT(*)                         AS count,
            ROUND(SUM(distance_km), 1)       AS km,
            ROUND(
                SUM(distance_km * COALESCE(efficiency_kwh_100km,0)) /
                NULLIF(SUM(CASE WHEN efficiency_kwh_100km IS NOT NULL THEN distance_km END), 0),
                1
            ) AS avg_eff
        FROM trips
        WHERE ended_at IS NOT NULL AND COALESCE(distance_km, 0) >= 0.1
        GROUP BY yr, mo_key, day_key
        ORDER BY started_at DESC
    """).fetchall()

    # Individual trip rows for day-level trip lists
    trip_rows = db.execute("""
        SELECT id, started_at, ended_at, distance_km, duration_min,
               efficiency_kwh_100km, start_soc, end_soc,
               COALESCE(untracked, 0) AS untracked
        FROM trips
        WHERE ended_at IS NOT NULL AND COALESCE(distance_km, 0) >= 0.1
        ORDER BY started_at DESC
    """).fetchall()
    trips_by_day: dict = {}
    for r in trip_rows:
        t = dict(r)
        if not t.get("started_at"):
            continue
        try:
            day_key = _parse_local(t["started_at"]).strftime("%Y-%m-%d")
        except Exception:
            continue
        trips_by_day.setdefault(day_key, []).append(t)

    years: dict = OrderedDict()
    for r in agg_rows:
        yr, mo_key, day_key = r["yr"], r["mo_key"], r["day_key"]
        count = r["count"]
        km = r["km"] or 0.0
        avg_eff = r["avg_eff"]

        # Format human-readable labels in Python (SQLite lacks %B)
        try:
            mo_label = datetime.strptime(mo_key, "%Y-%m").strftime("%B %Y")
            day_label = datetime.strptime(day_key, "%Y-%m-%d").strftime("%d %b %Y")
        except Exception:
            mo_label = mo_key
            day_label = day_key

        if yr not in years:
            years[yr] = {"label": yr, "km": 0.0, "count": 0,
                         "_ws": 0.0, "_wd": 0.0, "avg_eff": None,
                         "months": OrderedDict()}
        if mo_key not in years[yr]["months"]:
            years[yr]["months"][mo_key] = {"label": mo_label, "km": 0.0, "count": 0,
                                           "_ws": 0.0, "_wd": 0.0, "avg_eff": None,
                                           "days": OrderedDict()}

        day_node = {
            "label": day_label, "km": km, "count": count, "avg_eff": avg_eff,
            "trips": trips_by_day.get(day_key, []),
        }
        years[yr]["months"][mo_key]["days"][day_key] = day_node

        for node in (years[yr], years[yr]["months"][mo_key]):
            node["km"] = round(node["km"] + km, 1)
            node["count"] += count
            if avg_eff and km > 0:
                node["_ws"] += km * avg_eff
                node["_wd"] += km

    # Roll up weighted avg efficiency to month and year
    for yr_node in years.values():
        if yr_node["_wd"] > 0:
            yr_node["avg_eff"] = round(yr_node["_ws"] / yr_node["_wd"], 1)
        for mo_node in yr_node["months"].values():
            if mo_node["_wd"] > 0:
                mo_node["avg_eff"] = round(mo_node["_ws"] / mo_node["_wd"], 1)
            # Keep days as OrderedDict — template iterates .values()

    return list(years.values())


def get_trip_detail(trip_id: int) -> Optional[dict]:
    db = _get()
    trip = db.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
    if not trip:
        return None
    positions = db.execute(
        "SELECT latitude, longitude, speed_kmh, soc FROM trip_positions WHERE trip_id = ? ORDER BY id",
        (trip_id,),
    ).fetchall()
    return {
        **dict(trip),
        "positions": [dict(p) for p in positions],
    }


def get_charges(limit: int = 500) -> list[dict]:
    db = _get()
    rows = db.execute(
        "SELECT * FROM charges WHERE ended_at IS NOT NULL ORDER BY started_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_stats_grouped() -> list[dict]:
    """Trip stats nested as year → month → day (aggregated, no individual trips)."""
    from collections import OrderedDict
    db = _get()
    rows = db.execute("""
        SELECT
            strftime('%Y', started_at)    AS year,
            strftime('%Y-%m', started_at) AS month_key,
            date(started_at)              AS day_key,
            COUNT(*)                      AS trip_count,
            ROUND(SUM(distance_km), 1)    AS total_km,
            ROUND(SUM(distance_km * COALESCE(efficiency_kwh_100km, 0) / 100), 1) AS total_kwh,
            ROUND(
                SUM(distance_km * COALESCE(efficiency_kwh_100km, 0) / 100) /
                NULLIF(SUM(CASE WHEN efficiency_kwh_100km IS NOT NULL
                               THEN distance_km END), 0) * 100, 1
            ) AS avg_efficiency,
            ROUND(SUM(regen_kwh), 2) AS total_regen_kwh
        FROM trips
        WHERE ended_at IS NOT NULL
        GROUP BY year, month_key, day_key
        ORDER BY started_at DESC
    """).fetchall()

    years: dict = OrderedDict()
    for r in rows:
        d = dict(r)
        yr, mo_key, day_key = d["year"], d["month_key"], d["day_key"]

        # Format labels in Python (SQLite %B/%b not supported)
        try:
            mo_dt  = datetime.strptime(mo_key, "%Y-%m")
            mo_label = mo_dt.strftime("%B %Y")
            day_dt   = datetime.strptime(day_key, "%Y-%m-%d")
            d["day_label"] = day_dt.strftime("%d %b %Y")
        except Exception:
            mo_label = mo_key
            d["day_label"] = day_key

        if yr not in years:
            years[yr] = {"label": yr, "trip_count": 0, "total_km": 0.0,
                         "total_kwh": 0.0, "total_regen_kwh": 0.0,
                         "_ws": 0.0, "_wd": 0.0,
                         "avg_efficiency": None, "months": OrderedDict()}
        if mo_key not in years[yr]["months"]:
            years[yr]["months"][mo_key] = {"label": mo_label, "trip_count": 0,
                                           "total_km": 0.0, "total_kwh": 0.0,
                                           "total_regen_kwh": 0.0,
                                           "_ws": 0.0, "_wd": 0.0,
                                           "avg_efficiency": None, "days": []}

        years[yr]["months"][mo_key]["days"].append(d)

        km  = d.get("total_km") or 0
        eff = d.get("avg_efficiency")
        for node in (years[yr], years[yr]["months"][mo_key]):
            node["trip_count"]      += d["trip_count"]
            node["total_km"]         = round(node["total_km"] + km, 1)
            node["total_kwh"]        = round(node["total_kwh"] + (d.get("total_kwh") or 0), 1)
            node["total_regen_kwh"]  = round(node["total_regen_kwh"] + (d.get("total_regen_kwh") or 0), 2)
            if eff and km > 0:
                node["_ws"] += km * eff
                node["_wd"] += km

    for yr_node in years.values():
        if yr_node["_wd"] > 0:
            yr_node["avg_efficiency"] = round(yr_node["_ws"] / yr_node["_wd"], 1)
        for mo_node in yr_node["months"].values():
            if mo_node["_wd"] > 0:
                mo_node["avg_efficiency"] = round(mo_node["_ws"] / mo_node["_wd"], 1)
            mo_node["trips"] = []

    # Attach individual trips (chronological ASC) to each month for per-trip charts
    trip_rows = db.execute(
        """SELECT id, started_at, distance_km, efficiency_kwh_100km, regen_kwh
           FROM trips WHERE ended_at IS NOT NULL ORDER BY started_at ASC"""
    ).fetchall()
    for r in trip_rows:
        t = dict(r)
        if not t.get("started_at"):
            continue
        try:
            dt = _parse_local(t["started_at"])
        except Exception:
            continue
        yr, mo_key = dt.strftime("%Y"), dt.strftime("%Y-%m")
        t["label"] = dt.strftime("%d/%m %H:%M")
        if yr in years and mo_key in years[yr]["months"]:
            years[yr]["months"][mo_key]["trips"].append(t)

    return list(years.values())


def get_monthly_stats() -> list[dict]:
    db = _get()
    rows = db.execute(
        """SELECT
               strftime('%Y-%m', started_at, 'localtime') AS month,
               COUNT(*)                       AS trip_count,
               ROUND(SUM(distance_km), 1)     AS total_km,
               ROUND(SUM(CASE WHEN efficiency_kwh_100km IS NOT NULL
                              THEN distance_km END), 1) AS km_with_eff,
               ROUND(SUM(distance_km * COALESCE(efficiency_kwh_100km,0) / 100), 1) AS total_kwh,
               ROUND(AVG(efficiency_kwh_100km), 1) AS avg_efficiency
           FROM trips
           WHERE ended_at IS NOT NULL
           GROUP BY month
           ORDER BY month DESC
           LIMIT 12""",
    ).fetchall()
    return [dict(r) for r in rows]


def get_charges_grouped() -> list[dict]:
    """Return charges nested as year → month → day."""
    charges = get_charges()
    from collections import OrderedDict

    def _node(label):
        return {"label": label, "count": 0, "kwh": 0.0, "cost": 0.0, "has_cost": False, "months": OrderedDict()}

    def _day_node(label):
        return {"label": label, "count": 0, "kwh": 0.0, "cost": 0.0, "has_cost": False, "charges": []}

    years: dict = OrderedDict()
    for c in charges:
        if not c.get("started_at"):
            continue
        try:
            dt = _parse_local(c["started_at"])
        except Exception:
            continue

        yr  = dt.strftime("%Y")
        mo  = dt.strftime("%B %Y")
        day = dt.strftime("%d %b %Y")

        years.setdefault(yr, _node(yr))
        years[yr]["months"].setdefault(mo, {**_node(mo), "days": OrderedDict()})
        years[yr]["months"][mo]["days"].setdefault(day, _day_node(day))

        years[yr]["months"][mo]["days"][day]["charges"].append(c)

        kwh  = c.get("energy_added_kwh") or 0
        cost = c.get("cost") or 0
        for node in [years[yr], years[yr]["months"][mo], years[yr]["months"][mo]["days"][day]]:
            node["kwh"]   = round(node["kwh"] + kwh, 1)
            node["count"] += 1
            if c.get("cost") is not None:
                node["cost"]     = round(node["cost"] + cost, 2)
                node["has_cost"] = True

    return list(years.values())


def get_stats_summary() -> dict:
    db = _get()
    trips = db.execute(
        """SELECT
               COUNT(*)                                                       AS trip_count,
               ROUND(SUM(distance_km), 1)                                    AS total_km,
               ROUND(SUM(distance_km * COALESCE(efficiency_kwh_100km,0)/100), 1) AS total_kwh_used,
               ROUND(SUM(duration_min), 0)                                   AS total_drive_min,
               ROUND(
                   SUM(distance_km * COALESCE(efficiency_kwh_100km, 0)) /
                   NULLIF(SUM(CASE WHEN efficiency_kwh_100km IS NOT NULL THEN distance_km END), 0),
                   1
               ) AS avg_efficiency,
               ROUND(MIN(efficiency_kwh_100km), 1)                           AS best_efficiency,
               ROUND(SUM(regen_kwh), 1)                                      AS total_regen_kwh,
               ROUND(AVG(regen_kwh), 2)                                      AS avg_regen_kwh
           FROM trips WHERE ended_at IS NOT NULL"""
    ).fetchone()
    charges = db.execute(
        """SELECT
               COUNT(*)                         AS charge_count,
               ROUND(SUM(energy_added_kwh), 1)  AS total_kwh_charged,
               ROUND(SUM(cost), 2)              AS total_cost
           FROM charges WHERE ended_at IS NOT NULL"""
    ).fetchone()
    t = dict(trips) if trips else {}
    c = dict(charges) if charges else {}
    total_kwh = t.get("total_kwh_used") or 0
    total_regen = t.get("total_regen_kwh") or 0
    t["regen_pct"] = round(total_regen / total_kwh * 100, 1) if total_kwh > 0 else None
    return {**t, **c}


def get_charge_stats() -> dict:
    db = _get()
    row = db.execute(
        """SELECT
               COUNT(*)                            AS session_count,
               ROUND(SUM(energy_added_kwh), 1)    AS total_kwh,
               ROUND(AVG(duration_min / 60.0), 1) AS avg_duration_h,
               ROUND(SUM(cost), 2)                AS total_cost,
               ROUND(AVG(end_soc - start_soc), 1) AS avg_soc_delta,
               ROUND(MAX(max_power_kw), 1)        AS peak_power_kw
           FROM charges
           WHERE ended_at IS NOT NULL"""
    ).fetchone()
    return dict(row) if row else {}


def merge_trips(keep_id: int, drop_id: int) -> dict:
    """Merge drop_id into keep_id (keep_id must be the earlier trip). Returns updated trip."""
    from datetime import datetime
    db = _conn_rw()
    keep = db.execute("SELECT * FROM trips WHERE id=?", (keep_id,)).fetchone()
    drop = db.execute("SELECT * FROM trips WHERE id=?", (drop_id,)).fetchone()
    if not keep or not drop:
        return {}

    k = dict(keep)
    d = dict(drop)

    new_distance = round((k.get('distance_km') or 0) + (d.get('distance_km') or 0), 2)
    new_regen    = round((k.get('regen_kwh') or 0)   + (d.get('regen_kwh') or 0),   3)

    # Duration from start of keep to end of drop (includes the gap time)
    try:
        t_start = datetime.fromisoformat(k['started_at'].replace(' ', 'T').rstrip('Z'))
        t_end   = datetime.fromisoformat(d['ended_at'].replace(' ', 'T').rstrip('Z'))
        new_duration = round((t_end - t_start).total_seconds() / 60, 1)
    except Exception:
        new_duration = (k.get('duration_min') or 0) + (d.get('duration_min') or 0)

    # Efficiency: distance-weighted average
    k_eff, k_dist = k.get('efficiency_kwh_100km'), k.get('distance_km') or 0
    d_eff, d_dist = d.get('efficiency_kwh_100km'), d.get('distance_km') or 0
    if k_eff and d_eff and (k_dist + d_dist) > 0:
        new_eff = round((k_eff * k_dist + d_eff * d_dist) / (k_dist + d_dist), 1)
    elif k_eff:
        new_eff = k_eff
    else:
        new_eff = d_eff

    db.execute("""
        UPDATE trips
        SET ended_at=?, end_soc=?, end_odometer_km=?,
            distance_km=?, duration_min=?, efficiency_kwh_100km=?, regen_kwh=?
        WHERE id=?
    """, (d['ended_at'], d['end_soc'], d['end_odometer_km'],
          new_distance, new_duration, new_eff, new_regen, keep_id))

    db.execute("UPDATE trip_positions SET trip_id=? WHERE trip_id=?", (keep_id, drop_id))
    db.execute("DELETE FROM trips WHERE id=?", (drop_id,))
    db.commit()

    row = db.execute("SELECT * FROM trips WHERE id=?", (keep_id,)).fetchone()
    result = dict(row) if row else {}

    # Reset the read-only connection singleton so the next read sees the committed
    # data. In WAL mode the ro connection holds a read snapshot; without resetting
    # it, callers (e.g. get_trip_detail after the HX-Redirect) would still see the
    # pre-merge state.
    global _ro_conn
    if _ro_conn is not None:
        try:
            _ro_conn.close()
        except Exception:
            pass
        _ro_conn = None

    return result


def get_adjacent_trips(trip_id: int) -> tuple:
    """Returns (prev_trip, next_trip) — trips immediately before/after trip_id."""
    db = _get()
    trip = db.execute("SELECT started_at, ended_at FROM trips WHERE id=?", (trip_id,)).fetchone()
    if not trip:
        return None, None
    prev = db.execute(
        """SELECT * FROM trips WHERE ended_at IS NOT NULL AND ended_at < ?
           ORDER BY ended_at DESC LIMIT 1""",
        (trip['started_at'],)
    ).fetchone()
    nxt = db.execute(
        """SELECT * FROM trips WHERE started_at IS NOT NULL AND started_at > ?
           ORDER BY started_at ASC LIMIT 1""",
        (trip['ended_at'] or trip['started_at'],)
    ).fetchone()
    return (dict(prev) if prev else None), (dict(nxt) if nxt else None)


def get_ac_dc_stats() -> dict:
    """Count + energy of AC vs DC charge sessions. DC = charge_type 'DC', or (when not
    set) a measured peak power above 11 kW (AC tops out at ~11 kW; DC is faster)."""
    db = _get()
    rows = db.execute(
        "SELECT charge_type, max_power_kw, energy_added_kwh FROM charges WHERE ended_at IS NOT NULL"
    ).fetchall()
    ac = {"count": 0, "kwh": 0.0}
    dc = {"count": 0, "kwh": 0.0}
    for r in rows:
        ct = r["charge_type"]
        is_dc = ct == "DC" or (ct is None and (r["max_power_kw"] or 0) > 11)
        b = dc if is_dc else ac
        b["count"] += 1
        b["kwh"] += r["energy_added_kwh"] or 0
    ac["kwh"] = round(ac["kwh"], 1)
    dc["kwh"] = round(dc["kwh"], 1)
    return {"ac": ac, "dc": dc, "total": ac["count"] + dc["count"]}


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
        local_ts = _parse_local(trip["started_at"]).isoformat() if trip["started_at"] else None
        result.append({
            "trip_id":     trip["id"],
            "efficiency":  trip["efficiency_kwh_100km"],
            "started_at":  local_ts,
            "distance_km": trip["distance_km"],
            "points": [[p["latitude"], p["longitude"]] for p in pts],
        })
    return result


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
    result = []
    for r in rows:
        if r["outside_temp"] is None:
            continue
        d = dict(r)
        if d.get("started_at"):
            d["started_at"] = _parse_local(d["started_at"]).isoformat()
        result.append(d)
    return result


def get_monthly_charge_costs() -> list[dict]:
    db = _get()
    rows = db.execute(
        """SELECT
               strftime('%Y-%m', started_at, 'localtime') AS month,
               COALESCE(location_type,
                   CASE
                       WHEN max_power_kw <= 8  THEN 'HOME'
                       WHEN max_power_kw <= 22 THEN 'AC'
                       WHEN max_power_kw <= 80 THEN 'FAST'
                       ELSE 'HPC'
                   END
               ) AS charge_type,
               ROUND(SUM(cost), 2)             AS total_cost,
               ROUND(SUM(energy_added_kwh), 1) AS total_kwh,
               COUNT(*)                         AS session_count
           FROM charges
           WHERE ended_at IS NOT NULL
             AND started_at IS NOT NULL
           GROUP BY month, charge_type
           ORDER BY month ASC""",
    ).fetchall()
    return [dict(r) for r in rows]


def get_soc_history(days: int = 30) -> list[dict]:
    db = _get()
    if days > 0:
        rows = db.execute(
            """SELECT
                   strftime('%Y-%m-%dT%H:00:00', recorded_at, 'localtime') AS hour,
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
                   strftime('%Y-%m-%dT%H:00:00', recorded_at, 'localtime') AS hour,
                   ROUND(AVG(soc), 1) AS avg_soc
               FROM positions
               WHERE soc IS NOT NULL
               GROUP BY hour
               ORDER BY hour ASC""",
        ).fetchall()
    return [dict(r) for r in rows]


# ── Maintenance ──────────────────────────────────────────────────────────────

def _add_months(dt: datetime, months: int) -> datetime:
    """Add months to a datetime without dateutil dependency."""
    month = dt.month - 1 + months
    year  = dt.year + month // 12
    month = month % 12 + 1
    days_in_month = [31, 28 if year % 4 != 0 or (year % 100 == 0 and year % 400 != 0)
                     else 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return dt.replace(year=year, month=month, day=min(dt.day, days_in_month))


def _maintenance_status(item: dict, current_km: float | None, now: datetime) -> dict:
    """Augment an item dict with status/km_remaining/days_remaining/next_due fields."""
    result = dict(item)

    km_overdue = km_upcoming = False
    days_overdue = days_upcoming = False
    km_remaining = days_remaining = None

    if item["interval_km"] and item["last_done_km"] and current_km is not None:
        next_km     = item["last_done_km"] + item["interval_km"]
        km_remaining = next_km - current_km
        km_overdue  = km_remaining < 0
        km_upcoming = 0 <= km_remaining <= item["interval_km"] * 0.15

    if item["interval_months"] and item["last_done_date"]:
        try:
            last_dt        = datetime.strptime(item["last_done_date"], "%Y-%m-%d")
            next_dt        = _add_months(last_dt, item["interval_months"])
            days_remaining = (next_dt.date() - now.date()).days
            days_overdue  = days_remaining < 0
            days_upcoming = 0 <= days_remaining <= 30
        except Exception:
            pass

    mode = item["trigger_mode"]
    if mode == "km":
        overdue, upcoming = km_overdue, km_upcoming
    elif mode == "months":
        overdue, upcoming = days_overdue, days_upcoming
    elif mode == "both":
        overdue  = km_overdue and days_overdue
        upcoming = not overdue and (km_upcoming and days_upcoming)
    else:  # either (default)
        overdue  = km_overdue or days_overdue
        upcoming = not overdue and (km_upcoming or days_upcoming)

    result["status"]        = "overdue" if overdue else "upcoming" if upcoming else "ok"
    result["km_remaining"]  = int(km_remaining) if km_remaining is not None else None
    result["days_remaining"] = days_remaining

    # next_due helpers for the template
    if item["interval_km"] and item["last_done_km"]:
        result["next_due_km"] = int(item["last_done_km"] + item["interval_km"])
    else:
        result["next_due_km"] = None

    if item["interval_months"] and item["last_done_date"]:
        try:
            last_dt = datetime.strptime(item["last_done_date"], "%Y-%m-%d")
            result["next_due_date"] = _add_months(last_dt, item["interval_months"]).strftime("%Y-%m-%d")
        except Exception:
            result["next_due_date"] = None
    else:
        result["next_due_date"] = None

    return result


def get_maintenance_items(current_km: float | None = None) -> list[dict]:
    db  = _get()
    now = datetime.now()
    rows = db.execute("SELECT * FROM maintenance_items ORDER BY id").fetchall()
    return [_maintenance_status(dict(r), current_km, now) for r in rows]


def get_maintenance_logs(item_id: int | None = None, limit: int = 50) -> list[dict]:
    db = _get()
    if item_id is not None:
        rows = db.execute(
            "SELECT l.*, i.title FROM maintenance_logs l "
            "JOIN maintenance_items i ON i.id = l.item_id "
            "WHERE l.item_id = ? ORDER BY l.done_at DESC LIMIT ?",
            (item_id, limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT l.*, i.title FROM maintenance_logs l "
            "JOIN maintenance_items i ON i.id = l.item_id "
            "ORDER BY l.done_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def log_maintenance(item_id: int, odometer_km: float | None, cost: float | None,
                    provider: str, notes: str) -> dict:
    db       = _conn_rw()
    now_iso  = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT INTO maintenance_logs (item_id, done_at, odometer_km, cost, provider, notes)"
        " VALUES (?,?,?,?,?,?)",
        (item_id, now_iso, odometer_km or None, cost or None,
         provider or None, notes or None),
    )
    db.execute(
        "UPDATE maintenance_items SET last_done_km=?, last_done_date=? WHERE id=?",
        (odometer_km or None, now_iso[:10], item_id),
    )
    db.commit()
    global _ro_conn
    if _ro_conn is not None:
        try:
            _ro_conn.close()
        except Exception:
            pass
        _ro_conn = None
    row = db.execute("SELECT * FROM maintenance_items WHERE id=?", (item_id,)).fetchone()
    return dict(row) if row else {}


# ── Trip similarity ───────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(max(0.0, a)))


def _similarity_score(t: dict, c: dict) -> int:
    """Return a 0–100 similarity score. Returns 0 if any hard gate fails."""
    d1 = t.get("distance_km") or 0
    d2 = c.get("distance_km") or 0
    if d1 < 1 or d2 < 1:
        return 0
    if abs(d1 - d2) / min(d1, d2) > 0.40:
        return 0

    coords = ("start_lat", "start_lon", "end_lat", "end_lon")
    if not all(t.get(k) and c.get(k) for k in coords):
        return 0

    start_dist = _haversine_km(t["start_lat"], t["start_lon"], c["start_lat"], c["start_lon"])
    end_dist   = _haversine_km(t["end_lat"],   t["end_lon"],   c["end_lat"],   c["end_lon"])
    if start_dist > 5.0 or end_dist > 5.0:
        return 0

    time_score = 0.0
    try:
        h1 = _parse_local(t["started_at"]).hour + _parse_local(t["started_at"]).minute / 60.0
        h2 = _parse_local(c["started_at"]).hour + _parse_local(c["started_at"]).minute / 60.0
        diff_h = min(abs(h1 - h2), 24.0 - abs(h1 - h2))
        time_score = max(0.0, 1.0 - diff_h / 4.0)
    except Exception:
        pass

    coord_score = max(0.0, 1.0 - (start_dist + end_dist) / 10.0)
    dist_score  = max(0.0, 1.0 - abs(d1 - d2) / (0.40 * max(d1, d2)))

    return round((coord_score * 0.5 + dist_score * 0.3 + time_score * 0.2) * 100)


def get_similar_trips(trip_id: int, limit: int = 8, days: int = 365) -> list[dict]:
    """Return up to `limit` trips similar to trip_id, sorted by similarity score DESC."""
    db = _get()
    target_row = db.execute("SELECT * FROM trips WHERE id=?", (trip_id,)).fetchone()
    if not target_row:
        return []
    target = dict(target_row)
    if not all(target.get(k) for k in ("start_lat", "start_lon", "end_lat", "end_lon",
                                        "distance_km")):
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = db.execute(
        """SELECT t.*,
               (SELECT p.outside_temp
                FROM positions p
                WHERE p.recorded_at <= t.started_at
                  AND p.outside_temp IS NOT NULL
                ORDER BY p.recorded_at DESC LIMIT 1) AS outside_temp
           FROM trips t
           WHERE t.id != ?
             AND t.ended_at IS NOT NULL
             AND (t.untracked IS NULL OR t.untracked = 0)
             AND COALESCE(t.distance_km, 0) >= 1
             AND t.started_at >= ?
             AND t.start_lat IS NOT NULL
             AND t.end_lat IS NOT NULL
           ORDER BY t.started_at DESC
           LIMIT 500""",
        (trip_id, cutoff),
    ).fetchall()

    scored: list[dict] = []
    for row in rows:
        c = dict(row)
        score = _similarity_score(target, c)
        if score >= 30:
            c["similarity_score"] = score
            scored.append(c)

    scored.sort(key=lambda x: x["similarity_score"], reverse=True)
    return scored[:limit]
