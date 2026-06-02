"""LeapMotor Mate — vehicle data poller."""
import json
import logging
import os
import pathlib
import time

from db import Database
from recorder import Recorder

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("leapmotor_mate")


def _addon_option(key: str, default: str = "") -> str:
    """Read a Home Assistant add-on option without making Docker users depend on it."""
    path = os.environ.get("ADDON_OPTIONS_PATH", "/data/options.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            value = json.load(fh).get(key)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default
    return str(value) if value is not None else default


def _setting_env_option(db: "Database", db_key: str, env_key: str, default: str = "") -> str:
    return db.get_setting(db_key) or os.environ.get(env_key) or _addon_option(env_key, default)


def vehicle_source(db: "Database") -> str:
    return _setting_env_option(db, "vehicle_source", "VEHICLE_SOURCE", "leapmotor").lower()


def load_config(db: "Database") -> dict:
    """Load credentials from DB settings, falling back to env vars (dev mode).
    DB takes precedence over env — same order as the web layer — so a stray
    LEAPMOTOR_USER in the environment (or a mounted .env) can never silently
    switch the poller to a different account than the one set up in the wizard."""
    def _get(key_env: str, key_db: str, default: str = "") -> str:
        return _setting_env_option(db, key_db, key_env, default)

    return {
        "username":  _get("LEAPMOTOR_USER", "leapmotor_user"),
        "password":  _get("LEAPMOTOR_PASS", "leapmotor_pass"),
        "pin":       _get("LEAPMOTOR_PIN",  "leapmotor_pin", ""),
        "cert_path": _cert_path("app.crt", "CERT_PATH"),
        "key_path":  _cert_path("app.key", "KEY_PATH"),
    }


def load_ha_config(db: "Database") -> dict:
    return {
        "ha_url": _setting_env_option(db, "ha_url", "HA_URL"),
        "token": _setting_env_option(db, "ha_token", "HA_TOKEN"),
        "entity_prefix": _setting_env_option(
            db, "ha_entity_prefix", "HA_ENTITY_PREFIX",
            _setting_env_option(db, "mg4_entity_prefix", "MG4_ENTITY_PREFIX"),
        ),
    }


def _cert_path(filename: str, env_key: str) -> str:
    """Resolve the app cert/key: explicit env override → wizard-provided /data/certs →
    image-bundled certs/. The wizard writes user-provided certs to /data/certs (persistent),
    so a fresh install works without any cert baked into the image."""
    override = os.environ.get(env_key)
    if override:
        return override
    data_dir = os.environ.get("DATA_CERT_DIR", "/data/certs")
    data_path = os.path.join(data_dir, filename)
    if os.path.exists(data_path):
        return data_path
    return str(_PROJECT_ROOT / "certs" / filename)


def main():
    db_path = os.environ.get("DB_PATH", "leapmotor_mate.db")
    log.info("Starting LeapMotor Mate poller")

    db = Database(db_path)
    source = vehicle_source(db)

    # If no env vars set, wait for the setup wizard to complete
    if source == "leapmotor" and not os.environ.get("LEAPMOTOR_USER") and not db.is_setup_complete():
        log.info("Waiting for setup wizard...")
        while not db.is_setup_complete():
            time.sleep(5)
        log.info("Setup complete — starting poller")

    if source == "homeassistant":
        from ha_client import HomeAssistantMateClient

        cfg = load_ha_config(db)
        log.info("Using Home Assistant vehicle source: %s", cfg["ha_url"])
        client = HomeAssistantMateClient(**cfg)
    else:
        from client import LeapmotorMateClient

        cfg = load_config(db)
        _u = cfg["username"]
        _masked = (_u[:3] + "***" + _u[_u.find("@"):]) if "@" in _u else (_u[:3] + "***")
        device_id = db.get_or_create_device_id()
        log.info("Poller authenticating as account: %s | device_id: %s", _masked, device_id)
        client = LeapmotorMateClient(
            username=cfg["username"],
            password=cfg["password"],
            pin=cfg["pin"],
            cert_path=cfg["cert_path"],
            key_path=cfg["key_path"],
            device_id=device_id,
        )

    client.login()
    # Vehicle is known after login; register it in the DB
    v = client._vehicle
    vehicle_id = db.ensure_vehicle(v.vin, v.car_type, getattr(v, "year", None))

    if source == "homeassistant":
        capacity = getattr(client, "battery_capacity_kwh", None)
        if capacity:
            db.set_battery_capacity(capacity)
        db.set_setting("vehicle_source", "homeassistant")
        db.mark_setup_complete()
    elif not db.is_setup_complete():
        # First run: set battery capacity from per-model default
        # (will be overridable via setup wizard / settings UI)
        from db import default_capacity_for
        capacity = default_capacity_for(v.car_type)
        db.set_battery_capacity(capacity)
        log.info(
            "First run: %s default battery capacity set to %.1f kWh "
            "(change in Settings if you have a different variant)",
            v.car_type, capacity,
        )

    # Crash/restart recovery for open trips/charges happens on the first poll inside
    # Recorder._resume_or_close(), which RESUMES a still-ongoing session (avoiding
    # fragmentation) and only closes it if the activity has actually ended.
    recorder = Recorder(db, vehicle_id)

    log.info("Polling VIN %s (vehicle_id=%d)", v.vin, vehicle_id)

    while True:
        try:
            # Apply user-tunable poll cadence (Settings) live, each cycle
            try:
                recorder.set_poll_intervals(
                    int(db.get_setting("poll_parked", "30") or 30),
                    int(db.get_setting("poll_driving", "10") or 10),
                )
            except (TypeError, ValueError):
                pass
            data = client.get_status()
            recorder.process(data)
            interval = recorder.poll_interval
            # Boost window (set via POST /api/boost, e.g. an iPhone BT shortcut relayed
            # by HA when you get in the car): poll fast so we catch the trip start that
            # deep sleep would otherwise miss. Only matters while still parked — once
            # DRIVING the state machine already polls at 10s.
            try:
                boost_until = float(db.get_setting("boost_until", "0") or 0)
            except (TypeError, ValueError):
                boost_until = 0.0
            boosting = time.time() < boost_until and interval > 10
            if boosting:
                interval = 10
            log.info(
                "SOC %.1f%% | Range %d km | Speed %.0f km/h | State: %-8s | Gear: %s | Next poll: %ds%s",
                data.soc, data.range_km, data.speed_kmh,
                recorder.state.value, data.gear, interval,
                " (boost)" if boosting else "",
            )
            recorder.mark_online()
        except KeyboardInterrupt:
            log.info("Stopped by user")
            break
        except Exception as exc:
            log.error("Poll error: %s", exc)
            recorder.mark_offline()
            interval = recorder.poll_interval

        # Interruptible sleep: while parked we may be sleeping for minutes, so check the
        # boost flag every few seconds and wake immediately if one is requested.
        deadline = time.time() + interval
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            time.sleep(min(5.0, remaining))
            if interval > 10:
                try:
                    if float(db.get_setting("boost_until", "0") or 0) > time.time():
                        break   # boost just requested → poll now
                except (TypeError, ValueError):
                    pass

    client.close()
    db.close()


if __name__ == "__main__":
    main()
