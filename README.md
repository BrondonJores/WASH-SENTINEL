# WASH Sentinel — the dashboardless AI guardian for school water & sanitation

### Report in one sentence. The AI triages, prioritizes, assigns and follows up — online, on WhatsApp, and fully offline.

[![Stack](https://img.shields.io/badge/stack-Laravel%2012%20%7C%20React%2019%20%7C%20FastAPI-blue)]()
[![Tests](https://img.shields.io/badge/tests-59%20pytest%20%7C%20169%20PHPUnit%20methods-green)]()
[![Crypto](https://img.shields.io/badge/crypto-libsodium%20only-blue)]()
[![Offline](https://img.shields.io/badge/offline-mesh%20%7C%20SMS%20%7C%20USSD%20%7C%20QR-green)]()
[![Hackathon](https://img.shields.io/badge/hackathon-Meta-orange)]()

> **One sentence.** No more paper logs or chaotic calls: a school director reports a broken pump in plain
> language (console, WhatsApp voice note, or offline mesh), and WASH Sentinel turns it into a prioritized,
> assigned, tracked incident — automatically.
>
> **Docs:** [HACKATHON.md](docs/HACKATHON.md) (deep technical doc, EN) · [mesh protocol](mesh/README.md) ·
> [jury demo](docs/DEMO_JURY.md) · [deploy](docs/DEPLOY.md) · [field install](docs/INSTALL.md) ·
> [relay ops](docs/MESH_RUNBOOK.md) · [USSD](docs/USSD.md) · [WhatsApp live](docs/WHATSAPP_LIVE.md) ·
> [WhatsApp wiring](docs/WHATSAPP_BRANCHEMENT.md) · [classic demo](docs/DEMO.md)

Built for rural **Cameroon 🇨🇲** — pilot of the **Meta Hackathon**.

---

## 0. TL;DR for the jury (30 seconds)

Schools report broken pumps and sanitation failures through **five doors**: an AI console (French, role-based),
a public form (no login), WhatsApp (text + voice notes), and an **offline mesh** (phone-to-phone relay, QR,
SMS, USSD) for villages without coverage. Every report becomes a deduplicated, prioritized **incident** with
an audit trail, assignment, maintenance logs and follow-ups — no dashboard babysitting required.
The AI proposes; humans dispose: every AI write needs explicit confirmation (`oui`), and the full trail
lands in the journal.

---

## 1. The problem

- **Silent failures**: a broken pump can cut drinking water for 400+ pupils for weeks before anyone with
  authority hears about it (seed example: Bonanjo, 450 pupils without drinking water).
- **No connectivity**: remote schools have no data — web apps and WhatsApp are useless there.
- **Noisy channels**: reports arrive by calls, paper notes and word of mouth — duplicates, no priority, no follow-up.
- **No feedback loop**: reporters never learn what happened to their report, so they stop reporting.

## 2. The solution: one pipeline, five doors, one incident ledger

| Door | User | Channel | URL / access | Works offline |
|---|---|---|---|---|
| AI console `/` | admin, technician, director | web (FR), login + RBAC | `http://localhost:5173/` | no |
| Public form `/signaler` | anyone with a browser | web, **no login** | `http://localhost:5173/signaler` | no |
| WhatsApp | school contacts | text + voice notes + photos | Meta webhook `/api/v1/whatsapp/webhook` | no (needs Meta) |
| Mesh field app `/m` | directors, relay carriers | PWA / APK / desktop, QR carry | `http://localhost:5173/m` | **yes** |
| SMS / USSD | any 2G phone | `WASH <CODE> <TYPE>` / `*123#` menus | `/api/v1/mesh/sms`, `/api/v1/mesh/ussd` | **yes** |

Everything converges into `incidents`: deduped (text similarity + semantic threshold + photo hash, mesh
duplicates collapse by `bundle_id` first), scored (severity × exposure × recurrence), assigned, tracked,
and relanced when dormant.

## 3. Why this project wins 🏆

1. **Conversational-first, not form-first.** One sentence or voice note beats a 12-field form for a busy director.
2. **Privacy tiers.** Public form (no login), authenticated console (RBAC), sealed E2E mesh payloads relays can't read.
3. **Offline is the product.** Store-and-forward mesh (QR, Bluetooth, SMS, USSD) — not a degraded mode.
4. **Auditable AI.** Severity, dedup and assignments show their sources; every AI write needs explicit confirmation.
5. **Proven, not promised.** 59 pytest + 169 PHPUnit test methods, crypto interop vectors, chaos harness,
   live probes — and the one unproven claim (real radio) labeled as such.

## 4. Demo script (5 minutes, all local, detailed)

Prerequisites: `./start.sh` green, then open `http://localhost:5173`.
Seeded accounts (password `password` for all three): `admin@wash.cm` (Amina Ngo Bell, `wash_admin`),
`tech@wash.cm` (Jean Fotso, `maintenance_agent`), `directeur@ecole.cm` (Clarisse Eko, `school_reporter`).
Seed data: **8 schools** (Bonanjo, Libermann, Bali in Wouri; Ngok, Nkol in Mvila; Édéa, Pouuma, Nyo in
Sanaga-Maritime) and **9 incidents** (see [docs/DEMO_JURY.md](docs/DEMO_JURY.md) for the exact jury wording).

| Min | Step (exact clicks) | Expected |
|---|---|---|
| 0:00–0:45 | Login `admin@wash.cm` / `password` → console `/`. Type: `Nouveau signalement : école publique de Bonanjo, la pompe principale du puits est cassée depuis ce matin, 450 élèves sans eau potable.` | **"Confirmer le signalement"** card (`action_confirmation`): category `water_point`, urgency `critical`, affected pupils, **Confirmer** button |
| 0:45–1:30 | Type `Je veux signaler un problème d'eau à Ngok.` → answer the clarification questions → type exactly `oui` | Agent asks follow-ups (`prepare_report`), then `confirm_proposal` runs; **result card** with reference `WASH-2026-XXXXXX` |
| 1:30–2:30 | Type: `Ajoute une intervention au journal pour la panne d'eau : vidange et remplacement du joint, coût 250000 francs.` → click the right incident in the picker → type `oui` | **"Quel incident ?"** picker card (`incident_picker`); then **"Confirmer le journal"** card; maintenance log saved |
| 2:30–3:00 | On an incident card, click **"Détails"** (or click a school name in a ranking card) | **Side drawer** (`DetailDrawer`) with incident/school detail, cross-navigation, "ask a question" button |
| 3:00–3:35 | Type exactly: `Montre-moi la carte du territoire.` | **`territory_map`** card (`territory_overview` tool): schools, open incidents, affected pupils; equity contrast Bonanjo (critical, served) vs Pouuma (critical, unserved 31 days) |
| 3:35–4:10 | Type exactly: `Prépare un briefing du district de Wouri.` | **`briefing_deck`** card (`build_briefing`, `SlideDeck` component): presentation-ready mini-deck |
| 4:10–4:40 | Open `http://localhost:5173/signaler` (private window = no login): school `Bali` → type Point d'eau → urgency Haute → pupils `120` → send | **"Merci, c'est bien reçu !"** screen with reference `WASH-2026-XXXXXX` + urgency badge |
| 4:40–5:00 | WhatsApp variant: from `237600112233` (Bonanjo) send `Bonjour, le robinet du bloc A fuit beaucoup depuis hier.` (or simulator mode, no Meta needed) | Reply `WASH Sentinel : incident WASH-2026-XXXXXX enregistré…`, incident with `source: whatsapp`, async processing by the `queue` worker |

Offline encore (if time): airplane mode on `/m` → create report → QR → scan from another tab;
`python3 mesh/demo/simulate_hops.py --live` + `/admin/mesh` shows A→B→C hops and stats.
Plan B (cold model, AI down, cloud fallback) and the day-of checklist live in
[docs/DEMO_JURY.md](docs/DEMO_JURY.md) §§2–3.

---

## 5. Features by persona (everything the app does)

### 5.1 Admin (`wash_admin`) — console

- **Overview KPIs + map + trends**: `GET /api/v1/wash/overview` feeds the console (`ConsolePage`):
  incident counts, territory map (Leaflet), trend charts (Recharts).
- **Incidents lifecycle**: six statuses (`reported`, `triaged`, `assigned`, `in_progress`, `resolved`,
  `closed` — DB enum, default `reported`); validated transitions; `resolved_at` set automatically
  on `resolved`/`closed`; human override of AI priority (`POST …/override-priority`).
- **Assignment**: assign any incident to a technician (`POST …/assign`, sets status `assigned`);
  assignable-users picker (`GET /api/v1/wash/assignable-users`).
- **Reports inbox with AI analysis**: every report carries triage output (severity/type/school-match
  with sources); journal of AI analyses (`GET /api/v1/admin/ai-analyses`, `/admin/journal`).
- **Schools registry**: list/show/create (`/admin/ecoles`), 8 seeded Cameroonian schools with GPS,
  pupil counts, equipment type, installation year, replacement cost.
- **Maintenance logs per incident**: costed interventions (`MaintenanceLog`: amount in XAF,
  `repaired_at`, `days_without_service`); 4 seeded logs.
- **Dormant relaunch (relances)**: dry-run preview (`GET /relances/dormants`) then send
  (`POST /relances/dormants`) — e.g. the Pouuma borehole unserved for 31 days.
- **Notifications**: inbox (`/admin/notifications`), mark one/all read; critical-incident alerts.
- **Journal (audit)**: every AI action and confirmation (`AgentProposal` confirm/cancel flow) is logged
  and browsable at `/admin/journal` (admin-only).
- **Mesh monitor** (`/admin/mesh`): relay stats, pending bundles, bundle detail
  (`GET /api/v1/mesh/stats|bundles/pending|bundles/{id}`).
- **AI settings** (`/admin/reglages`, admin-only): LLM model profiles (Ollama local + external
  OpenAI-compatible providers) with **activate/test/warmup**; STT profiles with one-click test;
  hot switch without redeploy (e.g. Groq `llama-3.3-70b-versatile`).

### 5.2 Technician (`maintenance_agent`)

- Sees all incidents, edits them, updates statuses (`update incident status` permission).
- Records maintenance logs with cost and downtime; history feeds the **replace-vs-repair advisor**
  (`GET /api/v1/wash/agent/schools/{school}/replace-vs-repair`, deterministic thresholds on
  cumulative cost vs `estimated_replacement_cost`).
- Receives assignments and notifications; no access to `/admin/journal` or `/admin/reglages`.

### 5.3 Director / school reporter (`school_reporter`) + the public

- **Copilot chat** (console): natural-language dialogue with tool calls (11 tools in `AGENT_TOOLS`:
  `analyze_school`, `rank_schools_by_need`, `summarize_district`, `explain_incident`,
  `list_maintenance_logs`, `repair_trends`, `build_briefing`, `territory_overview`,
  `prepare_report`, `prepare_incident`, `prepare_maintenance_log`, plus plugin bundles).
- **Plan dispatch with confirmation**: the agent prepares (`prepare_*`), the human confirms (`oui` /
  `ok` / `je confirme` / `valider` / `d'accord`, regex in `WashAgentController::interceptVote`);
  `non` / `annuler` cancels — the AI never writes silently.
- **Epidemic scan**: deterministic multi-school symptom clustering
  (`POST /api/v1/wash/agent/epidemic-scan`, documented thresholds in `epidemic_detector.py`).
- **STT + vision**: voice notes transcribed via STT profiles (local whisper.cpp v1.7.4 / sherpa-onnx
  Omnilingual incl. Douala, or cloud `whisper-1`); photo tags feed severity (displayed, never silently fused).
- **WhatsApp**: text/voice/photo triage into the same pipeline; registration reply for unknown numbers
  (`ECOLE <nom>` flow); queued processing; simulator mode for dev (`WHATSAPP_SIMULATOR=true`);
  secret-less diagnostics endpoint.
- **Public form** `/signaler`: school autocomplete, type, urgency, pupils, description + photo;
  instant reference + dedup notice — no account needed.
- **Field app** `/m` (offline): install once, then airplane-proof — local outbox, QR show/scan,
  background sync, install prompt, outbox states.

### 5.4 Relay carrier (offline world)

- **PWA `/m`**: React + service worker (21 precache entries incl. `/m`); QR carry + upload.
- **Android APK**: Kotlin (Nearby P2P_CLUSTER + BLE GATT + SMS gateway + QR), Room + WorkManager,
  foreground relay + boot persistence, duty-cycled BLE; unit tests + `assembleDebug` in CI.
  Note: real Nearby/BLE radio never ran on hardware — labeled as the one unproven claim.
- **Desktop**: Neutralino wrapper (`wash-relai-desktop` v0.1.0, `@neutralinojs/neu` 11.2.0)
  booting on `/m` offline; CI artifact.
- **2G phones**: SMS `WASH <CODE> <TYPE>` (`P`=panne, `L`=latrine, `E`=eau, `H`=hygiène,
  1 segment ≤160 chars, allowlist + quotas) and guided USSD menus on `*123#` (fictional code
  pending an operator contract).
- iPhones capture, carry (QR) and upload; they can't background-relay (Apple limits) — the APKs do that job.

## 6. CRUD vs. Sentinel

| Classic CRUD | WASH Sentinel |
|---|---|
| Manual entry | Conversational + voice + offline capture |
| Flat list | Scored, deduplicated incidents |
| No follow-up | Assignment, logs, dormant relaunch |
| Online only | Mesh + SMS + USSD for zero-coverage villages |

## 7. Formulas (documented, tunable)

| Output | Formula |
|---|---|
| Severity | type weight × exposure (pupils) × recurrence |
| Priority | severity × vulnerability × days-open |
| Dedup | text similarity + semantic threshold + photo hash (+ `bundle_id` for mesh) |
| Relance | dormant N days + no activity → dry-run preview → send |
| Replace-vs-repair | cumulative maintenance cost vs `estimated_replacement_cost` + recurrence |

Thresholds live in code and seeders (`thresholds.py`, `repair_advisor.py`, `epidemic_detector.py`),
all covered by tests. Fallbacks are deterministic and provable: keyword extraction
(`IncidentTriageService::fallbackExtraction`, `model_used: fallback-rules`), ignored vision with warning,
no silent dedup, deterministic agent summary (`AgentLoop::_fallback_answer`).

---

## 8. Architecture

```text
                         ┌──────────────┐  :80
                    ┌────│ Laravel 12   │── API + triage + incidents
                    │    │ Sanctum/RBAC │── queue worker (async WA/mesh)
                    │    └──────▲───────┘
        ┌───────────┼───────────┼──────────────────┐
        │           │           │                  │
   ┌────┴────┐ ┌────┴────┐ ┌────┴─────┐      ┌─────┴──────┐  :5173
   │Console/ │ │WhatsApp │ │ Mesh     │ :8001│ React 19   │
   │public   │ │webhook  │ │ relay    │◄─────│ PWA+console│
   │form     │ │(Meta)   │ │ FastAPI  │ sync │ offline /m │
   └─────────┘ └─────────┘ └────▲─────┘      └────────────┘
                          QR/BT/WiFi/SMS/USSD
                          ┌────┴──────┐  ┌───────────┐  ┌────────┐
                          │ Android   │  │ iPhone    │  │ 2G     │
                          │ relay APK │  │ PWA carry │  │ phones │
                          └───────────┘  └───────────┘  └────────┘
   ┌──────────┐ :8000  ┌──────────┐ :11434
   │ai-engine │◄───────│ Ollama   │ (llama3.2:3b default, cloud fallback)
   │(Python)  │        │ LLM/STT  │
   └──────────┘        └──────────┘       ┌──────────┐ :5432
                                          │ Postgres │ (source of truth)
                                          └──────────┘
```

| Service | Host port → container | Role | Volume / notes |
|---|---|---|---|
| `laravel` | `${APP_PORT:-80}` → 8080 | API, triage, incidents, auth (`serversideup/php:8.3-fpm-nginx`) | `./backend` bind mount |
| `queue` | — | `queue:work --sleep=3 --tries=3 --timeout=120` async jobs | `./backend` bind mount |
| `pgsql` | `${FORWARD_DB_PORT:-5432}` → 5432 | Postgres 16-alpine, source of truth | `wash-pgsql` |
| `ai-engine` | `${FORWARD_AI_PORT:-8000}` → 8000 | Python NLP/STT/vision service (built from `./backend/ai-engine`) | `./models` bind mount |
| `ollama` | `${FORWARD_OLLAMA_PORT:-11434}` → 11434 | local LLM, `OLLAMA_KEEP_ALIVE=24h`, optional NVIDIA GPU | `wash-ollama` |
| `mesh-relay` | `${FORWARD_MESH_PORT:-8001}` → 8001 | store-and-forward + uplink w/ retry + circuit breaker | `mesh-relay-data` (`/data/relay.db`) |
| `frontend` | `${FRONTEND_PORT:-5173}` → 5173 | Vite dev (`node:22-alpine`, `npm install && npm run dev`) | `./frontend` + `wash-frontend-modules` |

7 services, 4 named volumes, 1 bridge network (`wash-network`). Relay env (from `compose.yaml`):
`LARAVEL_URL`, `MESH_INGEST_KEY`, `MESH_RELAY_API_KEY`, `MESH_DB_PATH`, `MESH_UPLINK_RETRIES=3`,
`MESH_UPLINK_BACKOFF=0.5`, breaker (5 fails, 60 s cooldown).

## 9. Tech stack (versions verified in manifests)

| Layer | Choice | Source |
|---|---|---|
| API | Laravel 12 (`^12.0`), PHP `^8.2` (runs 8.3-fpm-nginx), Sanctum `^4.0`, spatie/laravel-permission `^8.3` | `backend/composer.json` |
| Web | React `^19.3.1`, TS `~7.0.2`, Tailwind v4 `^4.3.3`, React Router `^7.18.5`, Leaflet `^1.9.4`, Recharts `^3.0.0` | `frontend/package.json` |
| Build/PWA | Vite `^8.3.5`, `@vitejs/plugin-react` `^6.1.2`, `vite-plugin-pwa` `^2.0.0`, oxlint `^1.89.0` | `frontend/package.json` |
| Relay/AI | Python `3.12-slim`, FastAPI `≥0.115`, PyNaCl `≥1.5`, httpx, sherpa-onnx `≥1.12`, piper-tts `≥1.2.0` | Dockerfiles + requirements |
| STT binaries | whisper.cpp `v1.7.4` (built from source, SDL2 off), Omnilingual ONNX, Piper TTS fr_FR | `backend/ai-engine/Dockerfile`, `compose.yaml` |
| Data | Postgres 16-alpine, SQLite (relay), localStorage (PWA outbox) | `compose.yaml`, `mesh/README.md` |
| Crypto | libsodium only: sealed boxes + Ed25519 (`libsodium-wrappers ^0.8.4` in TS) | `frontend/package.json`, `mesh/README.md` |
| LLM | Ollama (`ollama/ollama:latest`): `llama3.2:3b`, `nomic-embed-text`, optional `llama3.2-vision:11b` | `.env.example`, `start.sh` |
| Mobile | Kotlin APK (Nearby + BLE + SMS + QR), Neutralino desktop (`neu 11.2.0`) | `mesh/android`, `desktop/package.json` |
| Infra | Docker Compose, 7 services, 4 volumes, one-command start | `compose.yaml`, `start.sh`/`stop.sh` |

## 10. Repository map

```text
.
├── README.md              # this file — showcase + complete guide
├── docs/                  # HACKATHON.md (deep tech) · DEMO_JURY.md · DEMO.md · INSTALL.md
│                          # DEPLOY.md · MESH_RUNBOOK.md · USSD.md · WHATSAPP_LIVE.md
│                          # WHATSAPP_BRANCHEMENT.md
├── backend/               # Laravel 12 API (app/ · routes/ · tests/ · database/)
├── backend/ai-engine/     # Python NLP/STT/vision service (app/*.py, Dockerfile)
├── frontend/              # React 19 console + public form + offline PWA /m
├── mesh/                  # protocol: sdk/ · server/ (relay+tests) · demo/ (harness) · android/ (APK)
├── desktop/               # Neutralino wrapper (offline /m binary)
├── models/                # local STT/TTS models (created by start.sh, git-ignored weights)
├── compose.yaml + start.sh / stop.sh · CI: backend·frontend·relay·android·desktop·ai-engine
└── .github/workflows/ci.yml
```

---

## 11. Quickstart

**Prerequisites:** Docker + Compose plugin, 2 GB RAM (cloud-LLM profile) or ~8 GB (local Ollama),
ports 80/5173/5432/8000/8001/11434 free. `start.sh` refuses to run without the Docker daemon
and prints the 4 usual fixes (daemon off, snap, group permissions, engine missing).

```bash
git clone https://github.com/BrondonJores/WASH-SENTINEL && cd WASH-SENTINEL
./start.sh   # containers + key + migrate --force + seed + Ollama models
```

What `start.sh` does, in order: copies root/backend/frontend `.env` from examples; creates
`models/{omnilingual,whisper,piper}`; fixes `storage/` permissions; `docker compose up -d --build`;
waits for Postgres (`pg_isready`) and Laravel; `storage:link` + `migrate --force` + `db:seed --force`
(8 schools, 9 incidents, roles, AI profiles); waits for Ollama; pulls `llama3.2:3b`
(non-blocking on failure — switch to an external profile in Réglages IA) + `nomic-embed-text`;
prints the URLs.

| Entry point | URL |
|---|---|
| Console (login) | `http://localhost:5173/` |
| Public form (no login) | `http://localhost:5173/signaler` |
| Field app (offline) | `http://localhost:5173/m` |
| Mesh monitor | `http://localhost:5173/admin/mesh` |
| AI settings | `http://localhost:5173/admin/reglages` |
| API | `http://localhost/api` (`APP_PORT`, default 80) |
| AI engine docs | `http://localhost:8000/docs` |
| Relay health | `http://localhost:8001/health` |

Stop: `./stop.sh` (data kept) or `./stop.sh --volumes` (wipes DB + Ollama models).
Production (VPS + HTTPS + checklists): [docs/DEPLOY.md](docs/DEPLOY.md).

## 12. Usage guide by role

**Admin (console):** triage the reports inbox → confirm AI severity → assign to a technician →
track maintenance logs → close; relaunch dormant incidents (dry-run first); monitor `/admin/mesh`
for offline traffic; tune LLM/STT profiles in `/admin/reglages`.

**Technician:** open assigned incidents → update status → log interventions with cost and downtime →
watch recurrence via the replace-vs-repair advisor.

**Director online:** public form `/signaler` (no login) or WhatsApp message/voice note to the school
number → automatic incident + reply.

**Director offline:** PWA `/m` (install once, then airplane-proof): fill the form → stored locally →
show the QR to any carrier (Android relay, taxi-moto phone, iPhone) → the bundle hops until someone
uploads. No smartphone? Text `WASH <CODE> <TYPE>` (e.g. `WASH DOU-BON-001 P`) or dial the USSD menus
from any 2G phone.

**Relay carrier (Android APK):** start the relay once (foreground + boot persistence) → the phone
gossips Nearby, falls back to BLE, queues SMS gateway traffic, and uploads everything on signal.

## 13. Frontend routes (all of them, from `frontend/src/App.tsx`)

| Path | Page | Access |
|---|---|---|
| `/login` | `LoginPage` — Sanctum token login | public |
| `/m` | `MeshFieldPage` — offline field app (lazy) | public, installable |
| `/signaler` | `PublicReportPage` — public report form (lazy) | public, no login |
| `/` | `ConsolePage` — AI console, KPIs, map, trends, chat | authenticated |
| `/admin/incidents` | `IncidentsPage` — incident list + lifecycle | authenticated |
| `/admin/ecoles` | `SchoolsPage` — schools registry | authenticated |
| `/admin/signalements` | `ReportsPage` — reports inbox + AI analysis | authenticated |
| `/admin/journal` | `JournalPage` — audit journal | **admin-only** (`wash_admin`) |
| `/admin/notifications` | `NotificationsPage` — notifications inbox | authenticated |
| `/admin/mesh` | `MeshPage` — mesh monitor (stats, pending, bundles) | authenticated |
| `/admin/reglages` | `SettingsPage` — LLM/STT profiles | **admin-only** (`wash_admin`) |
| `/admin`, `*` | redirect to `/` | — |

Non-admins hitting an admin-only route see `Accès réservé aux administrateurs WASH.` (`RequireAdmin`).

## 14. API overview (`/api`, JSON-only, from `backend/routes/api.php`)

Auth: `POST /api/v1/auth/token` (Sanctum, throttle 10/min), `DELETE /api/v1/auth/token`.
RBAC via `spatie/laravel-permission`: 12 permissions (`create reports`, `view own school reports`,
`view all incidents`, `edit incidents`, `assign incidents`, `update incident status`,
`override ai priority`, `use ai assistant`, `view ai analytics`, `manage schools`, `manage users`,
`manage ai settings`) across 3 roles (`school_reporter`, `maintenance_agent`, `wash_admin`).

| Domain | Endpoints |
|---|---|
| Schools | `GET /v1/wash/schools`, `GET /v1/wash/schools/{school}`, `POST /v1/wash/schools` (`manage schools`) |
| Reports | `GET /v1/wash/reports[/{id}]`, `POST /v1/wash/reports` (throttle 60/min) |
| Incidents | `GET /v1/wash/incidents[/{id}]`, `GET /v1/wash/overview`, `PATCH …/status`, `POST …/assign`, `POST …/override-priority`, `POST …/maintenance-logs`, `GET /v1/wash/assignable-users` |
| Relances | `GET /v1/wash/relances/dormants` (dry-run), `POST /v1/wash/relances/dormants` (send) |
| Agent | `POST /v1/wash/agent/chat`, `POST …/converse` (30/min), `POST …/dispatch-plan`, `POST …/epidemic-scan`, `POST …/synthesize`, `POST …/transcribe` (30/min), `GET …/schools/{school}/replace-vs-repair` |
| Proposals | `POST /v1/wash/agent/proposals/{id}/confirm`, `POST …/cancel` (30/min each) |
| Social | `GET /v1/wash/library`, projects CRUD (`index/store/update/destroy`), conversations (`store/update/destroy/replaceMessages`) |
| Admin/AI | `GET /v1/admin/ai-analyses`, `GET …/provider-types`, `…/stt-types`, model-profiles + stt-profiles CRUD with `…/activate` and `…/test` (`manage ai settings`) |
| Notifications | `GET /v1/notifications`, `POST …/read-all`, `POST …/{notification}/read` |
| Mesh | `POST /v1/mesh/bundles`, `POST …/sms`, `POST …/ussd` (60/min each), `GET …/ussd` (probe), `GET …/key`, `GET …/bundles/pending`, `GET …/bundles/{id}`, `GET …/stats` |
| WhatsApp | `GET /v1/whatsapp/webhook` (verify), `POST …/webhook` (receive, 60/min), `GET …/diagnostics` |

Relay (`:8001`, `X-Mesh-Key` iff `MESH_RELAY_API_KEY` set; `/health` and `/metrics` stay open):
`GET /health|/metrics|/v1/stats`, `POST /v1/store|fetch|sync|ack|uplink`, `WS /v1/ws/{node_id}` (`?key=` auth).

AI engine (`:8000`, see `backend/ai-engine/app/main.py`): `GET /health`, `POST /v1/wash/extract`,
`POST /v1/wash/check-duplicates`, `POST /v1/wash/analyze-image`, `POST /v1/wash/generate-repair-plan`,
`POST /v1/wash/detect-epidemic-risk`, `POST /v1/wash/equity/dispatch-plan`,
`POST /v1/wash/copilot/chat`, `POST /v1/wash/copilot/replace-vs-repair`,
`POST /v1/voice/transcribe`, `POST /v1/voice/synthesize`, `POST /v1/wash/triage`,
`POST /v1/wash/rag/ask`, `POST /v1/wash/recurrence-watch`, admin `provider-types|test-provider|warmup|stt-types|test-stt|ai-metrics`.

## 15. Data models (all 15 in `backend/app/Models/`)

| Model | Role |
|---|---|
| `User` | Sanctum-authenticated account (admin/tech/director) with spatie roles |
| `School` | school registry: code, district, GPS, pupils, equipment, replacement cost |
| `SchoolContact` | verified phone ↔ school binding (WhatsApp/SMS identity), 5 seeded |
| `Report` | raw incoming report (text/voice/photo, channel, dedup flags) |
| `Incident` | the ledger entry: category, issue type, status, urgency, score, assignee, `WASH-YYYY-XXXXXX` reference |
| `MaintenanceLog` | costed intervention on an incident (XAF, downtime days) |
| `AiAnalysis` | stored triage output shown in the journal |
| `AgentProposal` | pending AI write awaiting confirm/cancel |
| `AiModelProfile` | LLM provider profile (Ollama local / external OpenAI-compatible) |
| `AiSttProfile` | STT provider profile (local whisper/Omnilingual / cloud) |
| `MeshBundle` | ingested offline bundle (UUID dedup, origin, hops) |
| `MeshNodeKey` | TOFU pubkey memory per origin node (`key_changed` alerts) |
| `Conversation` / `Message` | copilot dialogue persistence + library |
| `Project` | user workspace grouping for conversations |

## 16. Security & privacy 🔒

- **RBAC on all mutations**: 12 permissions × 3 roles; admin-only journal and AI settings; permission
  middleware on every write route (`manage schools`, `assign incidents`, `override ai priority`, …).
- **Throttles**: public writes 60/min (reports, mesh bundles/SMS/USSD, WhatsApp receive), agent
  converse/transcribe/proposals 30/min, auth tokens 10/min.
- **Secrets fail closed**: diagnostics endpoints expose booleans, never secrets; confirmed-fixes only.
- **Mesh authenticity**: Ed25519 signatures verified at relay ingress **and** on direct Laravel upload;
  TOFU key memory (`mesh_node_keys`) raises `mesh.node.key_changed` on change — accepted, never silently.
- **E2E confidentiality**: libsodium sealed boxes open exclusively on the server (`MESH_SEAL_SECRET`);
  relays and carriers only see routing metadata; no PII (names/phones) in bundles.
- **Quotas**: SMS 10/day/sender, mesh 500/day/origin; school must exist; honest downgrades
  (no server key → 503 → cleartext **with a warning**; SMS always cleartext by design).
- **AI safety rails**: proposal confirm/cancel flow, validated status transitions, contradiction guard,
  full journal — the AI never writes silently.

## 17. Testing & QA

| Suite | Command | Count |
|---|---|---|
| Relay + frames + harness | `pytest mesh/server mesh/demo` (excl. vendored `.venv`) | **59** |
| Laravel mesh (bundles, media, SMS, USSD, sig, TOFU) | `php artisan test --filter 'WashMesh\|WashSms\|WashUssd\|MeshSig\|MeshNodeKey'` | **56** |
| WhatsApp (webhook, triage, diagnostics) | `php artisan test --filter WashWhatsApp` | **12** |
| Full Laravel suite | `php artisan test` (24 Feature + 2 Unit files) | **169 test methods** |
| AI engine | `python -m pytest tests/ -q` (in CI `ai-engine` job) | covered in CI |
| Android unit + APK | CI `testDebugUnitTest` + `assembleDebug` | 5 test files |
| Frontend | `tsc -b`, `npm run build`, `npm run lint` (oxlint) | 0 errors |

Beyond unit tests: a **golden crypto vector** reproduced byte-for-byte in TS/Python/PHP with real
libsodium; a **3-relay chaos harness** (kill -9, TTL, duplicates) in CI; a **live probe**
(`--live`) against real HTTP; QR round-trips and offline-first PWA verified in the production bundle.

## 18. Pilot budget (indicative, Cameroon 2026)

| Item | Estimate |
|---|---|
| VPS 2–4 GB + domain + HTTPS | ~€6/mo + ~€10/yr |
| 2 relay Androids/zone (used) + solar | ~€60–100 one-off |
| Gateway data + reporter SMS | carrier rates, Mobile Money top-ups |
| USSD short code | operator quote required |

## 19. Roadmap

- [x] Console + RBAC + AI copilot (chat, plans, epidemic scan, STT/vision)
- [x] WhatsApp pipeline + public form + notifications + relances
- [x] Mesh v1→v3 + field app v1/v2 + signatures/TOFU + USSD + hardened APK
- [x] Chaos harness, P0 hardening, jury docs aligned
- [ ] Two-phone field validation (Nearby/BLE range + battery + duty cycle)
- [ ] Production VPS deploy · real operator USSD code · SMS gateway contract
- [ ] LoRa feasibility + ART regulatory check · iOS native spike · adaptive spray research

## 20. Known limitations (read before the jury asks)

- Real Nearby/BLE radio never ran on hardware — the one unproven claim, labeled everywhere it matters.
- iPhones can't background-relay (Apple); USSD code `*123#` is fictional pending an operator contract.
- Offline covers **collection**; consolidation still needs the server reachable.
- Relay SQLite is single-file (5k LRU), spray L=8 fixed, no congestion control, village clocks untrusted.
- Dev-first repo: `start.sh` targets local Docker; production needs [docs/DEPLOY.md](docs/DEPLOY.md).

## 21. Documentation index

| Doc | Content |
|---|---|
| [docs/HACKATHON.md](docs/HACKATHON.md) | deep technical documentation (this README's big sibling) |
| [docs/DEMO_JURY.md](docs/DEMO_JURY.md) | 5-minute jury script + plan B + day-of checklist |
| [docs/DEMO.md](docs/DEMO.md) | classic demo walkthrough |
| [docs/INSTALL.md](docs/INSTALL.md) | field installation guide |
| [docs/DEPLOY.md](docs/DEPLOY.md) | production VPS + HTTPS deployment |
| [docs/MESH_RUNBOOK.md](docs/MESH_RUNBOOK.md) | relay operations runbook |
| [docs/USSD.md](docs/USSD.md) | USSD gateway contract + curl examples |
| [docs/WHATSAPP_LIVE.md](docs/WHATSAPP_LIVE.md) | Meta live wiring runbook |
| [docs/WHATSAPP_BRANCHEMENT.md](docs/WHATSAPP_BRANCHEMENT.md) | WhatsApp wiring details |
| [mesh/README.md](mesh/README.md) | mesh protocol contract + threat model + honest limits |
| [mesh/android/README.md](mesh/android/README.md) | Android relay APK guide |

---

*WASH Sentinel — every school heard, with or without signal.* 💧🇨🇲
