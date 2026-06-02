# Remote Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mobile-first MG4 remote controls page that calls Home Assistant services for locks, climate, switches, numbers and selects.

**Architecture:** Add a focused `web/ha_commands.py` client that reads Home Assistant configuration from the same sources as the poller, discovers command entities from `/api/states`, and calls `/api/services/{domain}/{service}`. Add FastAPI routes and Jinja templates for the `/controls` page, keeping command logic out of templates.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, HTMX, Tailwind CDN, Home Assistant REST API, `unittest`.

---

## File Structure

- Create `web/ha_commands.py`: Home Assistant command client, entity discovery, service-call payload builders.
- Create `tests/test_ha_commands.py`: unit tests for discovery and service calls.
- Create `web/templates/controls.html`: full controls page.
- Create `web/templates/partials/controls_panel.html`: HTMX-refreshable controls content.
- Modify `web/main.py`: route `/controls`, route `/api/controls`, route `/api/controls/action`.
- Modify `web/templates/base.html`: add sidebar link.
- Modify `web/i18n.py`: add navigation/title/action labels.
- Modify `CHANGELOG.md`: record remote controls feature before release.

## Task 1: Home Assistant Command Client

**Files:**
- Create: `web/ha_commands.py`
- Test: `tests/test_ha_commands.py`

- [ ] **Step 1: Write failing discovery tests**

Create `tests/test_ha_commands.py` with:

```python
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))

from ha_commands import HomeAssistantCommandClient


PREFIX = "lsjwh4097rn111393"


def state(entity_id, value, **attributes):
    return {
        "entity_id": entity_id,
        "state": value,
        "attributes": attributes,
    }


class HomeAssistantCommandClientTest(unittest.TestCase):
    def test_discovers_available_remote_controls(self):
        client = HomeAssistantCommandClient(
            ha_url="https://example.invalid",
            token="secret",
            entity_prefix=PREFIX,
            fetch_states=lambda: [
                state(f"lock.{PREFIX}_doors_lock", "locked"),
                state(
                    f"climate.{PREFIX}_vehicle_climate",
                    "off",
                    hvac_modes=["off", "auto"],
                    min_temp=17,
                    max_temp=31,
                    target_temp_step=1,
                    temperature=23,
                    current_temperature=32,
                ),
                state(f"switch.{PREFIX}_front_window_defroster_heating", "off"),
                state(f"number.{PREFIX}_target_soc", "90", min=40, max=100, step=10, unit_of_measurement="%"),
                state(f"select.{PREFIX}_charge_current_limit", "Max", options=["6A", "8A", "16A", "Max"]),
            ],
            call_service=lambda domain, service, payload: {"ok": True},
        )

        controls = client.get_controls()

        self.assertEqual(controls["locks"]["doors"]["state"], "locked")
        self.assertEqual(controls["climate"]["state"], "off")
        self.assertEqual(controls["climate"]["temperature"], 23)
        self.assertEqual(controls["climate"]["min_temp"], 17)
        self.assertEqual(controls["switches"]["front_defroster"]["state"], "off")
        self.assertEqual(controls["numbers"]["target_soc"]["max"], 100)
        self.assertEqual(controls["selects"]["charge_current_limit"]["options"], ["6A", "8A", "16A", "Max"])
```

- [ ] **Step 2: Verify discovery test fails**

Run:

```bash
python3 -m unittest tests/test_ha_commands.py -v
```

Expected: fails with `ModuleNotFoundError: No module named 'ha_commands'`.

- [ ] **Step 3: Implement minimal discovery client**

Create `web/ha_commands.py` with:

```python
"""Home Assistant command client for MG4 remote controls."""
from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from typing import Any

StateFetcher = Callable[[], list[dict[str, Any]]]
ServiceCaller = Callable[[str, str, dict[str, Any]], Any]


class HomeAssistantCommandClient:
    def __init__(
        self,
        ha_url: str,
        token: str,
        entity_prefix: str,
        *,
        fetch_states: StateFetcher | None = None,
        call_service: ServiceCaller | None = None,
    ):
        self._ha_url = ha_url.rstrip("/")
        self._token = token
        self._entity_prefix = entity_prefix.lower()
        self._fetch_states = fetch_states or self._fetch_states_from_api
        self._call_service = call_service or self._call_service_api

    def get_controls(self) -> dict[str, Any]:
        states = self._state_map(self._fetch_states())
        return {
            "online": True,
            "locks": {
                "doors": self._entity_descriptor(states, "lock", "doors_lock"),
                "boot": self._entity_descriptor(states, "lock", "boot_lock"),
                "cable": self._entity_descriptor(states, "lock", "charging_cable_lock"),
            },
            "climate": self._climate_descriptor(states),
            "switches": {
                "front_defroster": self._entity_descriptor(states, "switch", "front_window_defroster_heating"),
                "rear_defroster": self._entity_descriptor(states, "switch", "rear_window_defroster_heating"),
                "fan_only": self._entity_descriptor(states, "switch", "vehicle_climate_fan_only"),
                "battery_heating": self._entity_descriptor(states, "switch", "battery_heating"),
                "charging": self._entity_descriptor(states, "switch", "charging"),
                "find_my_car": self._entity_descriptor(states, "switch", "find_my_car"),
            },
            "numbers": {
                "target_soc": self._number_descriptor(states, "target_soc"),
            },
            "selects": {
                "charge_current_limit": self._select_descriptor(states, "charge_current_limit"),
                "heated_seat_left": self._select_descriptor(states, "heated_seat_front_left_level"),
                "heated_seat_right": self._select_descriptor(states, "heated_seat_front_right_level"),
            },
        }

    def _entity(self, domain: str, suffix: str) -> str:
        return f"{domain}.{self._entity_prefix}_{suffix}"

    def _state_map(self, states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {
            s["entity_id"]: s
            for s in states
            if isinstance(s, dict)
            and isinstance(s.get("entity_id"), str)
            and s["entity_id"].split(".", 1)[-1].startswith(self._entity_prefix)
        }

    def _entity_descriptor(self, states: dict[str, dict[str, Any]], domain: str, suffix: str) -> dict[str, Any] | None:
        entity_id = self._entity(domain, suffix)
        item = states.get(entity_id)
        if not item:
            return None
        return {
            "entity_id": entity_id,
            "state": item.get("state", "unknown"),
            "available": item.get("state") not in {"unavailable", "unknown"},
            "friendly_name": (item.get("attributes") or {}).get("friendly_name", entity_id),
        }

    def _number_descriptor(self, states: dict[str, dict[str, Any]], suffix: str) -> dict[str, Any] | None:
        base = self._entity_descriptor(states, "number", suffix)
        if not base:
            return None
        attrs = states[base["entity_id"]].get("attributes") or {}
        base.update({
            "value": self._float(states[base["entity_id"]].get("state")),
            "min": self._float(attrs.get("min"), 0),
            "max": self._float(attrs.get("max"), 100),
            "step": self._float(attrs.get("step"), 1),
            "unit": attrs.get("unit_of_measurement", ""),
        })
        return base

    def _select_descriptor(self, states: dict[str, dict[str, Any]], suffix: str) -> dict[str, Any] | None:
        base = self._entity_descriptor(states, "select", suffix)
        if not base:
            return None
        attrs = states[base["entity_id"]].get("attributes") or {}
        base["options"] = attrs.get("options") or []
        return base

    def _climate_descriptor(self, states: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        base = self._entity_descriptor(states, "climate", "vehicle_climate")
        if not base:
            return None
        attrs = states[base["entity_id"]].get("attributes") or {}
        base.update({
            "temperature": self._float(attrs.get("temperature"), 21),
            "current_temperature": self._float(attrs.get("current_temperature")),
            "min_temp": self._float(attrs.get("min_temp"), 17),
            "max_temp": self._float(attrs.get("max_temp"), 31),
            "step": self._float(attrs.get("target_temp_step"), 1),
            "hvac_modes": attrs.get("hvac_modes") or [],
        })
        return base

    def _fetch_states_from_api(self) -> list[dict[str, Any]]:
        req = urllib.request.Request(
            f"{self._ha_url}/api/states",
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def _call_service_api(self, domain: str, service: str, payload: dict[str, Any]) -> Any:
        req = urllib.request.Request(
            f"{self._ha_url}/api/services/{domain}/{service}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body else {}

    @staticmethod
    def _float(value: Any, default: float | None = None) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
```

- [ ] **Step 4: Verify discovery test passes**

Run:

```bash
python3 -m unittest tests/test_ha_commands.py -v
```

Expected: `test_discovers_available_remote_controls ... ok`.

## Task 2: Service Action Methods

**Files:**
- Modify: `web/ha_commands.py`
- Test: `tests/test_ha_commands.py`

- [ ] **Step 1: Add failing service-call tests**

Append to `HomeAssistantCommandClientTest`:

```python
    def test_calls_expected_home_assistant_services(self):
        calls = []
        client = HomeAssistantCommandClient(
            ha_url="https://example.invalid",
            token="secret",
            entity_prefix=PREFIX,
            fetch_states=lambda: [],
            call_service=lambda domain, service, payload: calls.append((domain, service, payload)) or {"ok": True},
        )

        client.lock_entity(f"lock.{PREFIX}_doors_lock")
        client.unlock_entity(f"lock.{PREFIX}_doors_lock")
        client.turn_on_switch(f"switch.{PREFIX}_charging")
        client.turn_off_switch(f"switch.{PREFIX}_charging")
        client.turn_on_climate(f"climate.{PREFIX}_vehicle_climate")
        client.turn_off_climate(f"climate.{PREFIX}_vehicle_climate")
        client.set_climate_temperature(f"climate.{PREFIX}_vehicle_climate", 22)
        client.set_number(f"number.{PREFIX}_target_soc", 80)
        client.select_option(f"select.{PREFIX}_charge_current_limit", "16A")

        self.assertEqual(calls, [
            ("lock", "lock", {"entity_id": f"lock.{PREFIX}_doors_lock"}),
            ("lock", "unlock", {"entity_id": f"lock.{PREFIX}_doors_lock"}),
            ("switch", "turn_on", {"entity_id": f"switch.{PREFIX}_charging"}),
            ("switch", "turn_off", {"entity_id": f"switch.{PREFIX}_charging"}),
            ("climate", "turn_on", {"entity_id": f"climate.{PREFIX}_vehicle_climate"}),
            ("climate", "turn_off", {"entity_id": f"climate.{PREFIX}_vehicle_climate"}),
            ("climate", "set_temperature", {"entity_id": f"climate.{PREFIX}_vehicle_climate", "temperature": 22}),
            ("number", "set_value", {"entity_id": f"number.{PREFIX}_target_soc", "value": 80}),
            ("select", "select_option", {"entity_id": f"select.{PREFIX}_charge_current_limit", "option": "16A"}),
        ])
```

- [ ] **Step 2: Verify service-call test fails**

Run:

```bash
python3 -m unittest tests/test_ha_commands.py -v
```

Expected: fails with `AttributeError: 'HomeAssistantCommandClient' object has no attribute 'lock_entity'`.

- [ ] **Step 3: Add service action methods**

Add these methods to `HomeAssistantCommandClient`:

```python
    def lock_entity(self, entity_id: str) -> Any:
        return self._call_service("lock", "lock", {"entity_id": entity_id})

    def unlock_entity(self, entity_id: str) -> Any:
        return self._call_service("lock", "unlock", {"entity_id": entity_id})

    def turn_on_switch(self, entity_id: str) -> Any:
        return self._call_service("switch", "turn_on", {"entity_id": entity_id})

    def turn_off_switch(self, entity_id: str) -> Any:
        return self._call_service("switch", "turn_off", {"entity_id": entity_id})

    def turn_on_climate(self, entity_id: str) -> Any:
        return self._call_service("climate", "turn_on", {"entity_id": entity_id})

    def turn_off_climate(self, entity_id: str) -> Any:
        return self._call_service("climate", "turn_off", {"entity_id": entity_id})

    def set_climate_temperature(self, entity_id: str, temperature: float) -> Any:
        return self._call_service("climate", "set_temperature", {"entity_id": entity_id, "temperature": temperature})

    def set_number(self, entity_id: str, value: float) -> Any:
        return self._call_service("number", "set_value", {"entity_id": entity_id, "value": value})

    def select_option(self, entity_id: str, option: str) -> Any:
        return self._call_service("select", "select_option", {"entity_id": entity_id, "option": option})

    def _call_service(self, domain: str, service: str, payload: dict[str, Any]) -> Any:
        if not payload.get("entity_id", "").startswith(f"{domain}.{self._entity_prefix}_"):
            raise ValueError("entity_id does not belong to this MG4")
        return self._call_service(domain, service, payload)
```

When adding `_call_service`, rename the constructor field from `self._call_service` to `self._service_caller` and update `_call_service_api` usage to avoid name collision.

- [ ] **Step 4: Verify service-call test passes**

Run:

```bash
python3 -m unittest tests/test_ha_commands.py -v
```

Expected: both tests pass.

## Task 3: FastAPI Routes

**Files:**
- Modify: `web/main.py`
- Modify: `web/db_reader.py`
- Test: `tests/test_ha_commands.py`

- [ ] **Step 1: Add configuration helper**

Add a helper in `web/main.py`:

```python
def _addon_option(key: str, default: str = "") -> str:
    path = os.environ.get("ADDON_OPTIONS_PATH", "/data/options.json")
    try:
        import json
        with open(path, "r", encoding="utf-8") as fh:
            value = json.load(fh).get(key)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default
    return str(value) if value is not None else default


def _ha_command_client():
    from ha_commands import HomeAssistantCommandClient

    ha_url = db_reader.get_setting("ha_url") or os.environ.get("HA_URL") or _addon_option("HA_URL")
    token = db_reader.get_setting("ha_token") or os.environ.get("HA_TOKEN") or _addon_option("HA_TOKEN")
    prefix = (
        db_reader.get_setting("ha_entity_prefix")
        or os.environ.get("HA_ENTITY_PREFIX")
        or _addon_option("HA_ENTITY_PREFIX")
        or (db_reader.get_vehicle()[0] or {}).get("vin", "").lower()
    )
    return HomeAssistantCommandClient(ha_url, token, prefix)
```

- [ ] **Step 2: Add controls page and panel routes**

Add to `web/main.py`:

```python
@app.get("/controls", response_class=HTMLResponse)
async def controls_page(request: Request):
    vehicle, _ = db_reader.get_vehicle()
    controls = _safe_controls()
    return templates.TemplateResponse(request, "controls.html", _ctx(
        page="controls", vehicle=vehicle, controls=controls, feedback=None,
    ))


@app.get("/api/controls", response_class=HTMLResponse)
async def controls_panel(request: Request):
    controls = _safe_controls()
    return templates.TemplateResponse(request, "partials/controls_panel.html", _ctx(
        controls=controls, feedback=None,
    ))


def _safe_controls(feedback: dict | None = None) -> dict:
    try:
        controls = _ha_command_client().get_controls()
    except Exception as exc:
        controls = {"online": False, "error": str(exc), "locks": {}, "switches": {}, "numbers": {}, "selects": {}, "climate": None}
    if feedback:
        controls["feedback"] = feedback
    return controls
```

- [ ] **Step 3: Add command action route**

Add to `web/main.py`:

```python
@app.post("/api/controls/action", response_class=HTMLResponse)
async def controls_action(request: Request):
    form = await request.form()
    action = str(form.get("action", ""))
    entity_id = str(form.get("entity_id", ""))
    client = _ha_command_client()
    feedback = {"ok": True, "message": "Command sent"}
    try:
        if action == "lock":
            client.lock_entity(entity_id)
        elif action == "unlock":
            client.unlock_entity(entity_id)
        elif action == "switch_on":
            client.turn_on_switch(entity_id)
        elif action == "switch_off":
            client.turn_off_switch(entity_id)
        elif action == "climate_on":
            client.turn_on_climate(entity_id)
        elif action == "climate_off":
            client.turn_off_climate(entity_id)
        elif action == "climate_temp":
            client.set_climate_temperature(entity_id, float(form.get("value")))
        elif action == "number":
            client.set_number(entity_id, float(form.get("value")))
        elif action == "select":
            client.select_option(entity_id, str(form.get("value", "")))
        else:
            raise ValueError(f"Unsupported action: {action}")
    except Exception as exc:
        feedback = {"ok": False, "message": str(exc)}
    return templates.TemplateResponse(request, "partials/controls_panel.html", _ctx(
        controls=_safe_controls(feedback), feedback=feedback,
    ))
```

- [ ] **Step 4: Compile route changes**

Run:

```bash
python3 -m py_compile web/main.py web/ha_commands.py web/db_reader.py
```

Expected: exit code 0.

## Task 4: Controls Templates

**Files:**
- Create: `web/templates/controls.html`
- Create: `web/templates/partials/controls_panel.html`
- Modify: `web/templates/base.html`
- Modify: `web/i18n.py`

- [ ] **Step 1: Add sidebar nav**

In `web/templates/base.html`, add after Vehicle:

```html
      <a href="controls"    class="nav-link {% if page=='controls'    %}active{% endif %}">
        <span class="text-lg">🎛️</span> {{ t('nav_controls') }}
      </a>
```

- [ ] **Step 2: Add i18n labels**

Add keys in English and Italian dictionaries in `web/i18n.py`:

```python
"nav_controls": "Controls",
"controls_title": "Remote controls",
"controls_subtitle": "Commands exposed by Home Assistant for your MG4.",
```

Italian:

```python
"nav_controls": "Comandi",
"controls_title": "Comandi remoti",
"controls_subtitle": "Comandi esposti da Home Assistant per la tua MG4.",
```

- [ ] **Step 3: Create page shell**

Create `web/templates/controls.html`:

```html
{% extends "base.html" %}
{% block title %}{{ t('controls_title') }} — MG4 Mate{% endblock %}
{% block content %}

<div class="mb-6">
  <h1 class="text-2xl font-bold text-white">{{ t('controls_title') }}</h1>
  <p class="text-slate-400 text-sm">{{ t('controls_subtitle') }}</p>
</div>

<div id="controls-panel"
     hx-get="api/controls"
     hx-trigger="load, every 20s"
     hx-swap="innerHTML">
  {% include "partials/controls_panel.html" %}
</div>

{% endblock %}
```

- [ ] **Step 4: Create controls partial**

Create `web/templates/partials/controls_panel.html` with card-based forms:

```html
{% set locks = controls.get('locks', {}) %}
{% set switches = controls.get('switches', {}) %}
{% set numbers = controls.get('numbers', {}) %}
{% set selects = controls.get('selects', {}) %}
{% set climate = controls.get('climate') %}

{% macro action_button(label, action, entity_id, value=None, tone='brand') -%}
<form hx-post="api/controls/action" hx-target="#controls-panel" hx-swap="innerHTML" class="inline">
  <input type="hidden" name="action" value="{{ action }}">
  <input type="hidden" name="entity_id" value="{{ entity_id }}">
  {% if value is not none %}<input type="hidden" name="value" value="{{ value }}">{% endif %}
  <button type="submit" class="px-3 py-2 rounded-lg text-sm font-semibold {% if tone == 'danger' %}bg-red-500 hover:bg-red-400{% else %}bg-brand hover:bg-teal-400{% endif %} text-white">
    {{ label }}
  </button>
</form>
{%- endmacro %}

{% if controls.get('feedback') %}
<div class="mb-4 rounded-lg border px-4 py-3 text-sm {% if controls.feedback.ok %}border-green-700 bg-green-950 text-green-200{% else %}border-red-700 bg-red-950 text-red-200{% endif %}">
  {{ controls.feedback.message }}
</div>
{% endif %}

{% if not controls.get('online', True) %}
<div class="card border-red-900 bg-red-950/40 text-red-200 text-sm">
  Home Assistant controls unavailable: {{ controls.get('error', 'unknown error') }}
</div>
{% else %}

<section class="mb-5 rounded-xl border border-slate-700 bg-slate-800 overflow-hidden">
  <div class="p-5 grid grid-cols-1 md:grid-cols-[1fr_220px] gap-5 items-center">
    <div>
      <div class="text-xs uppercase tracking-wider text-brand font-bold">MG4 remote</div>
      <div class="text-2xl font-black text-white mt-1">Cockpit</div>
      <div class="text-sm text-slate-400 mt-2">
        Doors: {{ locks.get('doors', {}).get('state', 'n/a') }} ·
        Climate: {{ climate.state if climate else 'n/a' }}
        {% if climate and climate.temperature is not none %}· {{ climate.temperature|int }}°C{% endif %}
      </div>
    </div>
    <div class="relative h-40 rounded-2xl bg-slate-900 border border-slate-700">
      <div class="absolute left-1/2 top-5 -translate-x-1/2 w-20 h-28 rounded-[2rem] bg-slate-700 border border-slate-500 shadow-2xl"></div>
      <div class="absolute left-5 top-5 text-xs rounded-full bg-slate-800 border border-slate-600 px-3 py-2">🔒 {{ locks.get('doors', {}).get('state', 'n/a') }}</div>
      <div class="absolute right-5 bottom-5 text-xs rounded-full bg-slate-800 border border-slate-600 px-3 py-2">❄️ {{ climate.temperature|int if climate and climate.temperature is not none else '--' }}°</div>
    </div>
  </div>
</section>

<div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
  <section class="card">
    <h2 class="font-semibold text-white mb-4">Sicurezza</h2>
    <div class="space-y-3">
      {% for key, label in [('doors', 'Porte'), ('boot', 'Bagagliaio'), ('cable', 'Cavo ricarica')] %}
        {% set item = locks.get(key) %}
        {% if item %}
        <div class="flex items-center justify-between gap-3 bg-slate-900 rounded-lg p-3">
          <div><div class="text-white text-sm font-semibold">{{ label }}</div><div class="text-xs text-slate-400">{{ item.state }}</div></div>
          <div class="flex gap-2">
            {{ action_button('Blocca', 'lock', item.entity_id) }}
            {{ action_button('Sblocca', 'unlock', item.entity_id, tone='danger') }}
          </div>
        </div>
        {% endif %}
      {% endfor %}
    </div>
  </section>

  <section class="card">
    <h2 class="font-semibold text-white mb-4">Clima</h2>
    {% if climate %}
    <div class="bg-slate-900 rounded-lg p-3 mb-3">
      <div class="flex items-center justify-between">
        <div><div class="text-white text-sm font-semibold">Clima abitacolo</div><div class="text-xs text-slate-400">{{ climate.state }} · target {{ climate.temperature|int }}°C</div></div>
        <div class="flex gap-2">{{ action_button('On', 'climate_on', climate.entity_id) }}{{ action_button('Off', 'climate_off', climate.entity_id, tone='danger') }}</div>
      </div>
      <div class="flex items-center justify-between mt-4">
        {{ action_button('−', 'climate_temp', climate.entity_id, climate.temperature - climate.step) }}
        <div class="text-2xl font-bold text-white">{{ climate.temperature|int }}°</div>
        {{ action_button('+', 'climate_temp', climate.entity_id, climate.temperature + climate.step) }}
      </div>
    </div>
    {% endif %}
    <div class="space-y-3">
      {% for key, label in [('fan_only', 'Solo ventola'), ('front_defroster', 'Sbrina frontale'), ('rear_defroster', 'Sbrina posteriore')] %}
        {% set item = switches.get(key) %}
        {% if item %}
        <div class="flex items-center justify-between bg-slate-900 rounded-lg p-3">
          <div><div class="text-white text-sm font-semibold">{{ label }}</div><div class="text-xs text-slate-400">{{ item.state }}</div></div>
          {% if item.state == 'on' %}{{ action_button('Off', 'switch_off', item.entity_id, tone='danger') }}{% else %}{{ action_button('On', 'switch_on', item.entity_id) }}{% endif %}
        </div>
        {% endif %}
      {% endfor %}
    </div>
  </section>
</div>

{% endif %}
```

- [ ] **Step 5: Compile templates by importing app**

Run:

```bash
PYTHONPATH=web python3 -c 'import main; print("web import ok")'
```

Expected: prints `web import ok`.

## Task 5: Complete Remaining Control Sections

**Files:**
- Modify: `web/templates/partials/controls_panel.html`

- [ ] **Step 1: Add charging and battery card**

Append a third card below the first grid:

```html
<div class="grid grid-cols-1 lg:grid-cols-2 gap-5 mt-5">
  <section class="card">
    <h2 class="font-semibold text-white mb-4">Ricarica e batteria</h2>
    {% set charging = switches.get('charging') %}
    {% if charging %}
    <div class="flex items-center justify-between bg-slate-900 rounded-lg p-3 mb-3">
      <div><div class="text-white text-sm font-semibold">Ricarica</div><div class="text-xs text-slate-400">{{ charging.state }}</div></div>
      {% if charging.state == 'on' %}{{ action_button('Stop', 'switch_off', charging.entity_id, tone='danger') }}{% else %}{{ action_button('Avvia', 'switch_on', charging.entity_id) }}{% endif %}
    </div>
    {% endif %}
    {% set battery_heating = switches.get('battery_heating') %}
    {% if battery_heating %}
    <div class="flex items-center justify-between bg-slate-900 rounded-lg p-3 mb-3">
      <div><div class="text-white text-sm font-semibold">Battery heating</div><div class="text-xs text-slate-400">{{ battery_heating.state }}</div></div>
      {% if battery_heating.state == 'on' %}{{ action_button('Off', 'switch_off', battery_heating.entity_id, tone='danger') }}{% else %}{{ action_button('On', 'switch_on', battery_heating.entity_id) }}{% endif %}
    </div>
    {% endif %}
    {% set target = numbers.get('target_soc') %}
    {% if target %}
    <form hx-post="api/controls/action" hx-target="#controls-panel" hx-swap="innerHTML" class="bg-slate-900 rounded-lg p-3 mb-3">
      <input type="hidden" name="action" value="number">
      <input type="hidden" name="entity_id" value="{{ target.entity_id }}">
      <div class="flex justify-between text-sm"><span class="text-white font-semibold">Target SOC</span><span class="text-brand font-bold"><span id="target-soc-val">{{ target.value|int }}</span>%</span></div>
      <input name="value" type="range" min="{{ target.min|int }}" max="{{ target.max|int }}" step="{{ target.step|int }}" value="{{ target.value|int }}" oninput="document.getElementById('target-soc-val').textContent=this.value" class="w-full accent-brand mt-3">
      <button class="mt-3 px-3 py-2 rounded-lg bg-brand text-white text-sm font-semibold">Imposta</button>
    </form>
    {% endif %}
    {% set limit = selects.get('charge_current_limit') %}
    {% if limit %}
    <div class="bg-slate-900 rounded-lg p-3">
      <div class="text-white text-sm font-semibold mb-2">Limite corrente</div>
      <div class="flex flex-wrap gap-2">
        {% for option in limit.options %}
        {{ action_button(option, 'select', limit.entity_id, option) }}
        {% endfor %}
      </div>
    </div>
    {% endif %}
  </section>
```

- [ ] **Step 2: Add comfort and utility card**

Append:

```html
  <section class="card">
    <h2 class="font-semibold text-white mb-4">Comfort e utility</h2>
    {% for key, label in [('heated_seat_left', 'Sedile guidatore'), ('heated_seat_right', 'Sedile passeggero')] %}
      {% set seat = selects.get(key) %}
      {% if seat %}
      <div class="bg-slate-900 rounded-lg p-3 mb-3">
        <div class="flex justify-between items-center mb-2"><div class="text-white text-sm font-semibold">{{ label }}</div><div class="text-xs text-slate-400">{{ seat.state }}</div></div>
        <div class="flex flex-wrap gap-2">
          {% for option in seat.options %}
          {{ action_button(option, 'select', seat.entity_id, option) }}
          {% endfor %}
        </div>
      </div>
      {% endif %}
    {% endfor %}
    {% set find = switches.get('find_my_car') %}
    {% if find %}
    <div class="flex items-center justify-between bg-slate-900 rounded-lg p-3">
      <div><div class="text-white text-sm font-semibold">Find my car</div><div class="text-xs text-slate-400">{{ find.state }}</div></div>
      {{ action_button('Attiva', 'switch_on', find.entity_id) }}
    </div>
    {% endif %}
  </section>
</div>
```

- [ ] **Step 3: Verify app import**

Run:

```bash
PYTHONPATH=web python3 -c 'import main; print("web import ok")'
```

Expected: prints `web import ok`.

## Task 6: Verification, Commit, and Release Prep

**Files:**
- Modify: `CHANGELOG.md`
- Source commit to `ghianciulu/mg4-mate`
- Add-on update in `../leapmotor-mate-addon`

- [ ] **Step 1: Run full local checks**

Run:

```bash
python3 -m unittest tests/test_ha_client.py tests/test_ha_commands.py -v
python3 -m py_compile poller/ha_client.py poller/vehicle_data.py poller/recorder.py poller/state_machine.py poller/main.py web/main.py web/db_reader.py web/ha_commands.py
PYTHONPATH=web python3 -c 'import main; print("web import ok")'
rg -n "QETseWJ8|eyJhbGciOiJIUzI1Ni|HA_TOKEN='" .
```

Expected:

- Unit tests pass.
- Compile exits 0.
- Web import prints `web import ok`.
- Token scan returns no matches.

- [ ] **Step 2: Update changelog**

Add to `CHANGELOG.md`:

```markdown
## Unreleased

- Added Home Assistant-backed MG4 remote controls page.
- Added controls for locks, climate, defrosters, charging, target SOC, current limit, heated seats and find-my-car when exposed by Home Assistant.
```

- [ ] **Step 3: Commit source**

Run:

```bash
git add CHANGELOG.md tests/test_ha_commands.py web/ha_commands.py web/main.py web/i18n.py web/templates/base.html web/templates/controls.html web/templates/partials/controls_panel.html
git commit -m "feat: add Home Assistant remote controls"
```

- [ ] **Step 4: Push source**

Run:

```bash
git push fork mg4-homeassistant:main
git push fork mg4-homeassistant
```

- [ ] **Step 5: Update add-on pin and version**

Get the source commit hash:

```bash
git rev-parse --short HEAD
```

Then set `ARG MATE_REF` in `../leapmotor-mate-addon/mg4_mate/Dockerfile` to that returned hash. If `git rev-parse --short HEAD` prints `abc1234`, the Dockerfile line becomes:

```dockerfile
ARG MATE_REF=abc1234
```

In `../leapmotor-mate-addon/mg4_mate/config.yaml`, bump version by one patch.

In `../leapmotor-mate-addon/mg4_mate/CHANGELOG.md`, add the new version with remote controls notes.

- [ ] **Step 6: Verify and push add-on**

Run in `../leapmotor-mate-addon`:

```bash
python3 -m json.tool repository.json
rg -n "version:|ARG MATE_REF|leapmotor|LeapMotor|Leapmotor|LEAPMOTOR|leapmotor_mate" mg4_mate README.md repository.json
git add mg4_mate/Dockerfile mg4_mate/config.yaml mg4_mate/CHANGELOG.md
git commit -m "feat: release remote controls add-on"
git push fork main
```

Expected:

- JSON validates.
- Version and `ARG MATE_REF` show the new values.
- Legacy scan shows no old project references.

## Deferred Plan

Home Assistant history import remains in the approved design spec but is intentionally deferred to its own implementation plan after remote controls ship. The import touches persistence and recorder replay, so it should be tested and released independently.
