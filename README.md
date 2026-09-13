# HomeWatt — Smart Home Energy Usage Monitor

![HomeWatt dashboard](docs/dashboard.png)

A complete implementation of the project brief:

> **Day 1** — FastAPI + WebSocket streams power-usage readings per device
> (device name, watts, timestamp). `Readings` and `Usage_Alerts` tables.
> **Day 2** — Rules: a device uses way more power than normal, a device has been
> "on" for an unusually long time, total household usage crosses a threshold
> (budget limit). Score each alert by how far it is from normal; a stats check
> flags devices whose usage jumps far from its rolling average. A React
> dashboard shows live usage per device and any alerts.

Simulated smart-plug/appliance readings (12 realistic devices) replace the log
source, and everything is persisted in **PostgreSQL** (async SQLAlchemy 2.0 +
asyncpg, Alembic migrations).

---

## Tech stack

| Layer     | Technology                                            |
| --------- | ----------------------------------------------------- |
| Backend   | Python 3.13 · **FastAPI** · Uvicorn · Pydantic v2      |
| Database  | **PostgreSQL 17** · SQLAlchemy 2.0 (async) · asyncpg · Alembic |
| Stream    | FastAPI **WebSocket** fan-out (snapshot + tick frames) |
| Frontend  | **React 18** · TypeScript · Vite 5 · Recharts          |
| Design    | golden yellow `#E7B93C / #C9971C` · creamy beige `#F4ECDA / #FBF5E7` · warm brown `#4A2E1E / #2E1C11` |

---

## Run it

```bash
# everything (PostgreSQL → API :8000 → dashboard :5173)
./scripts/start_all.sh

# or individually
./scripts/setup_db.sh          # install/start postgres, create role+db
./scripts/start_backend.sh     # venv + alembic upgrade head + uvicorn
./scripts/start_frontend.sh    # npm install + vite dev (proxies /api → :8000)
```

* Dashboard → http://localhost:5173
* Interactive API docs → http://localhost:8000/docs

On first boot the backend seeds 12 smart plugs and back-fills **6 hours of
history** (8.6k readings) by replaying the same simulator and detection rules,
so charts and alert history are meaningful immediately. Re-runs are idempotent.

---

## Architecture

```
 ┌─────────────── PostgreSQL (energy_db) ───────────────┐
 │ devices │ readings │ usage_alerts │ settings        │
 └──────▲────────────▲──────────────▲───────────────────┘
        │            │              │
        │   ┌────────┴──────────────┴────────┐
        │   │  EnergyMonitor (asyncio task)  │  tick every 2 s
        │   │  simulator → readings          │
        │   │  AlertEngine → usage_alerts    │
        │   └────────┬───────────────────────┘
        │            │ broadcast (json)
 ┌──────┴──── FastAPI :8000 ──────────────────┐
 │ /api/devices  /api/readings  /api/alerts   │
 │ /api/stats    /api/settings  /api/ws/live  │◄──┐
 └────────────────────────────────────────────┘   │ ws
        ▲ REST                                    │
        │                                         │
 ┌──────┴──── Vite :5173 (React) ─────────────   │
 │ proxy /api ───────────────────────────────►├───┘
 │ Dashboard: KPIs · power chart · plug grid  │
 │ · alerts feed · thresholds editor          │
 └────────────────────────────────────────────┘
```

### Database schema (PostgreSQL)

| Table          | Purpose                                                                 |
| -------------- | ----------------------------------------------------------------------- |
| `devices`      | smart plugs: name, room, nominal/standby watts, duty-cycle profile, live state |
| `readings`     | one row per sample `(device_id, watts, is_on, ts)` — indexed on `(device_id, ts)` |
| `usage_alerts` | one row per detected anomaly: rule, severity, **score 0-100**, value vs baseline, ack flags |
| `settings`     | single row of tunable thresholds (budgets, z-score, cooldowns, tick)     |

Migrations live in `backend/alembic/versions/` (`alembic upgrade head`).

### Detection rules & scoring (`backend/app/detection.py`)

Every alert carries a **score 0-100** expressing *how far* the observation is
from normal: `score = 50 + 50·(1 − e^(−excess))` where `excess` is the relative
distance past the trigger (reaching the trigger already scores 50, 2× the
trigger saturates at 100). Severities: low ≥ 50, medium ≥ 65, high ≥ 80,
critical ≥ 90.

1. **spike** — device ON sample vs its rolling 60-min baseline of ON samples:
   z-score `(watts − μ)/max(σ, 5%μ, 1 W)`; fires at `z ≥ z_threshold` (default 3).
   The simple stats check from the brief.
2. **on_too_long** — continuous ON streak (from the last OFF reading) exceeds
   `max_on_minutes` (default 120).
3. **household_budget** — summed live load crosses `household_budget_watts` (4000 W).
4. **daily_energy** — projected daily kWh (`kWh_today ÷ hours_elapsed × 24`)
   crosses `daily_budget_kwh` (70 kWh), evaluated after 6 h elapsed.

All rules are de-duplicated by per-(device, rule) cooldowns (90 s; long-run
incidents get a 3 h cooldown). All thresholds are editable live from the
dashboard ("Detection & budgets" card → `PATCH /api/settings`).

### WebSocket protocol (`/api/ws/live`)

* on connect → `{"type":"snapshot", household, devices[12], recent_alerts}`
* every tick → `{"type":"tick", ts, household, devices[], alerts[]}` with
  per-device `watts, is_on, avg_watts (rolling μ), z_score, on_minutes,
  kwh_today, status ∈ {normal, watch, alert}`.

### REST surface (`/docs`)

```
GET    /api/devices            POST /api/devices        PATCH/DELETE /api/devices/{id}
GET    /api/readings?device_id&start&end&limit
GET    /api/readings/series?device_id&window=6h&points=180   (down-sampled charts)
GET    /api/alerts?rule&severity&acknowledged&limit     PATCH /api/alerts/{id}  POST /api/alerts/ack-all
GET    /api/alerts/stats?since_hours=24
GET    /api/stats/overview     GET /api/stats/energy-by-device
GET    /api/settings           PATCH /api/settings
POST   /api/simulator/start | /api/simulator/stop       GET /api/simulator/status
```

---

## Run on Windows

Full Arabic step-by-step guide → [`docs/WINDOWS_SETUP.md`](docs/WINDOWS_SETUP.md).
TL;DR: install Python 3.12 + Node LTS + PostgreSQL 17 (winget), create the
role/db once, then `powershell -ExecutionPolicy Bypass -File .\scripts\start_all_windows.ps1`.

## Run on a MacBook

Full Arabic step-by-step guide → [`docs/MACOS_SETUP.md`](docs/MACOS_SETUP.md).
TL;DR: `brew install git python@3.12 node postgresql@17`, then
`./scripts/setup_db.sh`, backend venv + `alembic upgrade head` + `uvicorn`,
frontend `npm install && npm run dev` — or just `./scripts/start_all.sh`.

## Push to GitHub

```bash
cd energy-monitor
git init -b main && git add . && git commit -m "HomeWatt: smart home energy monitor"

# 1) create an EMPTY repo on github.com (no README/license), then:
git remote add origin https://github.com/<YOUR_USERNAME>/energy-monitor.git
git push -u origin main

# …or with the GitHub CLI instead:
# gh auth login && gh repo create energy-monitor --public --source=. --remote=origin --push
```

## Layout

```
energy-monitor/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app, lifespan: migrate→seed→monitor
│   │   ├── models.py        # ORM: Device, Reading, UsageAlert, AppSettings
│   │   ├── schemas.py       # Pydantic v2 contracts
│   │   ├── simulator.py     # two-state appliance model (duty cycles, spikes)
│   │   ├── detection.py     # the four rules + scoring
│   │   ├── monitor.py       # tick loop: simulate→persist→detect→broadcast
│   │   ├── stats_service.py # rolling baselines, energy math (SQL aggregates)
│   │   ├── ws.py            # connection manager / fan-out
│   │   ├── seed.py          # 12 devices + 6 h back-fill + history replay
│   │   └── routers/         # devices · readings · alerts · stats · settings · stream
│   ├── alembic/             # PostgreSQL migrations
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx, hooks/useLiveEnergy.ts   # ws reconnect, snapshots, ticks
│       └── components/  Header · KpiCards · PowerChart · DeviceGrid ·
│                        AlertsPanel · SettingsPanel · Toasts
└── scripts/  setup_db.sh · start_backend.sh · start_frontend.sh · start_all.sh
```

## Design notes

The UI is a warm "electrical brass" theme: deep-brown chrome with a golden
bolt mark, creamy beige canvas, gold-gradient meters and score bars, rust-red
reserved for critical severity — serif display type (Georgia) over a clean
system sans.
