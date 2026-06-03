# MG4 Mate

Self-hosted companion app for MG4 vehicles. Tracks trips, charge sessions and vehicle status using data already published by the [SAIC MQTT Gateway](https://github.com/SAIC-iSmart-API/saic-python-mqtt-gateway) to Home Assistant.

> 🇮🇹 Versione italiana più sotto.

---

## Features

| Section | What you get |
|---|---|
| **Overview** | Live SOC, range, odometer, inside/outside temperature, AC target, charge state, last position on map |
| **Trips** | Automatic detection, GPS route map, distance, duration, efficiency (kWh/100 km), regeneration, SOC delta — auto and manual merge for split trips |
| **Charges** | Full sessions with SOC gain, estimated energy, peak power, duration, cost by charge type (Home/AC/Fast/HPC), manual correction of wrong SOC values |
| **Statistics** | Per-period summaries, distance-weighted average efficiency, regen totals |
| **Vehicle** | Tyre pressures with SVG top-down diagram, individual door & bonnet state, windows, lights, compass heading, 12 V aux battery, temperatures |
| **Controls** | Remote lock/unlock, climate, windows, charging on/off, target SOC, charge current limit, heated seats — all relayed via Home Assistant |
| **Settings** | Language (EN/IT), battery capacity, price per kWh by charge type, polling cadence, trip auto-merge gap |

---

## How it works

```
MG/iSMART cloud
      │
SAIC MQTT Gateway  →  Home Assistant entities
                               │
                        MG4 Mate poller  →  SQLite (local)
                               │
                          MG4 Mate web UI
```

MG4 Mate reads Home Assistant state data through the local REST API. It never contacts the MG cloud directly.

---

## Prerequisites

### 1. SAIC MQTT Gateway

The gateway connects your MG4 to Home Assistant via MQTT. Install it following the official instructions:

- **GitHub repo + Docker**: [github.com/SAIC-iSmart-API/saic-python-mqtt-gateway](https://github.com/SAIC-iSmart-API/saic-python-mqtt-gateway)
- **Home Assistant add-on**: available in the same repository

Once installed and configured, it publishes entities like `sensor.<vin>_soc`, `sensor.<vin>_range`, etc. to Home Assistant via MQTT discovery.

### 2. Home Assistant

Any recent version with MQTT integration enabled.

### 3. Long-lived access token

Generate one in Home Assistant under **Profile → Long-lived access tokens**.

---

## Installation — Home Assistant Add-on (recommended)

1. Go to **Settings → Add-ons → Add-on Store** in Home Assistant.
2. Click the **⋮** menu → **Repositories**.
3. Add:
   ```
   https://github.com/ghianciulu/mg4-mate-addon
   ```
4. Find **MG4 Mate** and click **Install**.
5. Fill in the options (see below) and click **Start**.
6. Open the add-on panel from the sidebar.

### Add-on options

| Option | Description |
|---|---|
| `VEHICLE_SOURCE` | Always `homeassistant` |
| `HA_URL` | Local URL of your HA instance, e.g. `http://192.168.1.10:8123` — use the local IP, not `homeassistant.local` |
| `HA_TOKEN` | Your long-lived access token |
| `HA_ENTITY_PREFIX` | Lower-case VIN prefix used in entity IDs (see below) |

**How to find your entity prefix:**

In Home Assistant, go to **Developer Tools → States** and search for your VIN. You will see entities like:

```
sensor.lsjwh4097rnxxxxxx_soc
```

The prefix is everything before `_soc`:

```
HA_ENTITY_PREFIX = lsjwh4097rnxxxxxx
```

---

## Installation — Standalone Docker

```bash
git clone https://github.com/ghianciulu/mg4-mate.git
cd mg4-mate
docker compose up -d
```

Set environment variables in `docker-compose.yml`:

```yaml
environment:
  VEHICLE_SOURCE: homeassistant
  HA_URL: http://192.168.1.10:8123
  HA_TOKEN: your_token_here
  HA_ENTITY_PREFIX: your_lowercase_vin
```

---

## Entities read from Home Assistant

MG4 Mate fetches these entities on every poll:

```
sensor.<prefix>_soc
sensor.<prefix>_range
sensor.<prefix>_mileage
sensor.<prefix>_vehicle_speed
sensor.<prefix>_power
sensor.<prefix>_current
sensor.<prefix>_voltage
sensor.<prefix>_exterior_temperature
sensor.<prefix>_interior_temperature
sensor.<prefix>_total_battery_capacity
sensor.<prefix>_remaining_charging_time
sensor.<prefix>_remote_climate_state
sensor.<prefix>_auxiliary_battery_voltage
sensor.<prefix>_heading
sensor.<prefix>_tyres_front_left_pressure
sensor.<prefix>_tyres_front_right_pressure
sensor.<prefix>_tyres_rear_left_pressure
sensor.<prefix>_tyres_rear_right_pressure
binary_sensor.<prefix>_vehicle_running
binary_sensor.<prefix>_battery_charging
binary_sensor.<prefix>_charger_connected
binary_sensor.<prefix>_boot
binary_sensor.<prefix>_bonnet
binary_sensor.<prefix>_door_driver
binary_sensor.<prefix>_door_passenger
binary_sensor.<prefix>_door_rear_left
binary_sensor.<prefix>_door_rear_right
binary_sensor.<prefix>_window_driver
binary_sensor.<prefix>_window_passenger
binary_sensor.<prefix>_window_rear_left
binary_sensor.<prefix>_window_rear_right
binary_sensor.<prefix>_lights_dipped_beam
binary_sensor.<prefix>_lights_main_beam
binary_sensor.<prefix>_lights_side
lock.<prefix>_doors_lock
climate.<prefix>_vehicle_climate
device_tracker.<prefix>_vehicle_position
```

Entities that return `unavailable` or `unknown` are silently skipped.

---

## Notes

- Polling the SAIC cloud does **not** wake the car or drain the 12 V battery — the gateway reads the last cached cloud state.
- Trip detection quality depends on the gateway refresh cadence. 30–60 s intervals while driving give good route maps.
- Never commit tokens. Pass them only through add-on options or environment variables.

---

## License

[GNU AGPL-3.0](./LICENSE)

---

---

# MG4 Mate 🇮🇹

App self-hosted per MG4. Registra viaggi, sessioni di ricarica e stato del veicolo usando i dati già pubblicati dal [SAIC MQTT Gateway](https://github.com/SAIC-iSmart-API/saic-python-mqtt-gateway) su Home Assistant.

---

## Funzionalità

| Sezione | Cosa trovi |
|---|---|
| **Panoramica** | SOC in tempo reale, autonomia, odometro, temperature interna/esterna, target AC, stato ricarica, ultima posizione su mappa |
| **Viaggi** | Rilevamento automatico, mappa percorso GPS, distanza, durata, efficienza (kWh/100 km), regen, delta SOC — unione automatica e manuale dei viaggi spezzati |
| **Ricariche** | Sessioni complete con guadagno SOC, energia stimata, potenza picco, durata, costo per tipo (Casa/AC/Fast/HPC), correzione manuale valori errati |
| **Statistiche** | Riepiloghi per periodo, efficienza media pesata sulla distanza, regen totale |
| **Veicolo** | Pressione gomme con diagramma SVG vista dall'alto, stato porte singole + cofano, finestrini, luci, direzione bussola, batteria ausiliaria 12 V, temperature |
| **Comandi** | Blocco/sblocco remoto, clima, finestrini, avvio/stop ricarica, target SOC, limite corrente, sedili riscaldati — tutto via Home Assistant |
| **Impostazioni** | Lingua (IT/EN), capacità batteria, prezzo per kWh per tipo di ricarica, cadenza polling, finestra unione viaggi automatica |

---

## Come funziona

```
Cloud MG/iSMART
      │
SAIC MQTT Gateway  →  Entità Home Assistant
                               │
                        MG4 Mate poller  →  SQLite (locale)
                               │
                          MG4 Mate interfaccia web
```

MG4 Mate legge i dati da Home Assistant tramite l'API REST locale. Non contatta mai il cloud MG direttamente.

---

## Prerequisiti

### 1. SAIC MQTT Gateway

Il gateway collega la tua MG4 a Home Assistant tramite MQTT. Segui le istruzioni ufficiali per installarlo:

- **GitHub repo + Docker**: [github.com/SAIC-iSmart-API/saic-python-mqtt-gateway](https://github.com/SAIC-iSmart-API/saic-python-mqtt-gateway)
- **Add-on Home Assistant**: disponibile nello stesso repository

Una volta configurato, pubblica entità come `sensor.<vin>_soc`, `sensor.<vin>_range`, ecc. su Home Assistant tramite MQTT discovery.

### 2. Home Assistant

Qualsiasi versione recente con l'integrazione MQTT attiva.

### 3. Token di accesso

Generalo in Home Assistant da **Profilo → Token di accesso di lunga durata**.

---

## Installazione — Add-on Home Assistant (consigliato)

1. Vai su **Impostazioni → Add-on → Store** in Home Assistant.
2. Menu **⋮** → **Repository**.
3. Aggiungi:
   ```
   https://github.com/ghianciulu/mg4-mate-addon
   ```
4. Trova **MG4 Mate** e clicca **Installa**.
5. Compila le opzioni (vedi sotto) e clicca **Avvia**.
6. Apri il pannello dell'add-on dalla barra laterale.

### Opzioni add-on

| Opzione | Descrizione |
|---|---|
| `VEHICLE_SOURCE` | Sempre `homeassistant` |
| `HA_URL` | URL locale di Home Assistant, es. `http://192.168.1.10:8123` — usa l'IP locale, non `homeassistant.local` |
| `HA_TOKEN` | Il tuo token di accesso |
| `HA_ENTITY_PREFIX` | Prefisso VIN minuscolo usato negli ID entità (vedi sotto) |

**Come trovare il prefisso entità:**

In Home Assistant vai su **Strumenti per sviluppatori → Stati** e cerca il tuo VIN. Vedrai entità come:

```
sensor.lsjwh4097rnxxxxxx_soc
```

Il prefisso è tutto quello prima di `_soc`:

```
HA_ENTITY_PREFIX = lsjwh4097rnxxxxxx
```

---

## Installazione — Docker standalone

```bash
git clone https://github.com/ghianciulu/mg4-mate.git
cd mg4-mate
docker compose up -d
```

Imposta le variabili d'ambiente in `docker-compose.yml`:

```yaml
environment:
  VEHICLE_SOURCE: homeassistant
  HA_URL: http://192.168.1.10:8123
  HA_TOKEN: il_tuo_token
  HA_ENTITY_PREFIX: vin_minuscolo
```

---

## Note

- Il polling del cloud SAIC **non sveglia** la macchina né consuma la batteria 12 V — il gateway legge l'ultimo stato in cache dal cloud.
- La qualità del tracciamento viaggi dipende dalla cadenza di aggiornamento del gateway. Intervalli di 30–60 secondi durante la guida producono buone mappe percorso.
- Non committare mai i token. Passali solo tramite le opzioni dell'add-on o variabili d'ambiente.

---

## Licenza

[GNU AGPL-3.0](./LICENSE)
