# WASH Sentinel — the dashboardless AI guardian for school water & sanitation

### Report in one sentence. The AI triages, prioritizes, assigns and follows up — online, on WhatsApp, and fully offline.

[![Stack](https://img.shields.io/badge/stack-Laravel%2012%20%7C%20React%2019%20%7C%20FastAPI-blue)]()
[![Tests](https://img.shields.io/badge/tests-59%20pytest%20%7C%2068%20PHPUnit%20mesh%2BWA-green)]()
[![Offline](https://img.shields.io/badge/offline-mesh%20%7C%20SMS%20%7C%20USSD%20%7C%20QR-green)]()
[![Hackathon](https://img.shields.io/badge/hackathon-Meta-orange)]()

> **One sentence.** No more paper logs or chaotic calls: a school director reports a broken pump in plain
> language (console, WhatsApp voice note, or offline mesh), and WASH Sentinel turns it into a prioritized,
> assigned, tracked incident — automatically.
>
> **Full documentation:** [docs/HACKATHON.md](docs/HACKATHON.md) (exhaustive, EN) · [mesh protocol](mesh/README.md) ·
> [jury demo](docs/DEMO_JURY.md) · [deploy](docs/DEPLOY.md)

Built for rural **Cameroon 🇨🇲** — pilot of the **Meta Hackathon**.

---

## 1. The problem

- **Silent failures** : a broken pump can cut drinking water for 400 pupils for weeks before anyone hears about it.
- **No connectivity** : remote schools have no data — web apps and WhatsApp are useless there.
- **Chaotic intake** : calls, paper notes, word of mouth — duplicates, no priority, no follow-up.
- **No feedback loop** : reporters never learn what happened, so they stop reporting.

## 2. What WASH Sentinel does

| Persona | Flow |
|---|---|
| School director (online) | public form `/signaler` or WhatsApp text/voice → incident + reply |
| School director (offline) | field app `/m` → local outbox → QR/Nearby/BLE/SMS/USSD → upload later |
| Technician | assigned incidents, maintenance logs, status transitions |
| Admin | console: KPIs, map, trends, mesh monitor, AI settings, audit journal |

**5-minute jury demo** (`./start.sh`, then `http://localhost:5173`, `admin@wash.cm` / `password`):
console → public report with photo → WhatsApp simulator → airplane-mode `/m` with QR hop →
`simulate_hops.py --live` + `/admin/mesh`. Details: [docs/DEMO_JURY.md](docs/DEMO_JURY.md).

## 3. Why this project wins 🏆

1. **Conversational-first, not form-first.** One sentence or voice note beats a 12-field form for a busy director.
2. **Privacy tiers.** Public form (no login), authenticated console (RBAC), sealed E2E mesh payloads relays can't read.
3. **Offline is the product.** Store-and-forward mesh (QR, Bluetooth, SMS, USSD) — not a degraded mode.
4. **Auditable AI.** Severity, dedup and assignments show their sources; every AI write needs explicit confirmation.
5. **Proven, not promised.** 59 + 68 tests, crypto interop vectors, chaos harness, live probes — and the one
   unproven claim (real radio) labeled as such.

## 4. Mobile & offline applications

No app-store gatekeeping for the pilot: the field app ships three ways.

| App | Tech | Install | Relay? |
|---|---|---|---|
| PWA `/m` | React + service worker | browser → Add to Home Screen | QR carry + upload |
| Android APK | Kotlin (Nearby + BLE + SMS + QR) | sideload / CI artifact | full background relay |
| Desktop | Neutralino wrapper of `/m` | double-click binary | QR carry + upload |

iPhones capture, carry (QR) and upload; they can't background-relay (Apple limits) — the APKs do that job.

## 5. CRUD vs. Sentinel

| Classic CRUD | WASH Sentinel |
|---|---|
| Manual entry | Conversational + voice + offline capture |
| Flat list | Scored, deduplicated incidents |
| No follow-up | Assignment, logs, dormant relaunch |
| Online only | Mesh + SMS + USSD for zero-coverage villages |

## 6. Formulas (documented, tunable)

| Output | Formula |
|---|---|
| Severity | type weight × exposure (pupils) × recurrence |
| Priority | severity × vulnerability × days-open |
| Dedup | text similarity + semantic threshold + photo hash (+ `bundle_id` for mesh) |
| Relance | dormant N days + no activity → dry-run preview → send |

Thresholds live in code and seeders, all covered by tests.

## 7. Architecture

```text
                    ┌──────────────┐  :80
               ┌────│ Laravel 12   │── API + triage + incidents
               │    │ Sanctum/RBAC │── queue worker (async)
               │    └──────▲───────┘
   ┌───────────┼───────────┼──────────────────┐
   │           │           │                  │
┌──┴────┐ ┌────┴────┐ ┌────┴─────┐      ┌─────┴──────┐  :5173
│Console│ │WhatsApp │ │ Mesh     │ :8001│ React 19   │
│+public│ │webhook  │ │ relay    │◄─────│ PWA+console│
│form   │ │(Meta)   │ │ FastAPI  │ sync │ offline /m │
└───────┘ └─────────┘ └────▲─────┘      └────────────┘
                     QR/BT/WiFi/SMS/USSD (APK · PWA · 2G)
┌──────────┐ :8000  ┌──────────┐ :11434      ┌──────────┐ :5432
│ai-engine │◄───────│ Ollama   │              │ Postgres │
│(Python)  │        │ LLM/STT  │              │ (truth)  │
└──────────┘        └──────────┘              └──────────┘
```

7 services (`laravel`, `queue`, `pgsql`, `ai-engine`, `ollama`, `mesh-relay`, `frontend`),
4 volumes (`wash-pgsql`, `mesh-relay-data`, `wash-ollama`, `wash-frontend-modules`).

## 8. Repository map

```text
├── README.md              # this file
├── docs/                  # HACKATHON.md · DEMO_JURY.md · DEMO.md · INSTALL.md
│                          # DEPLOY.md · MESH_RUNBOOK.md · USSD.md · WHATSAPP_LIVE.md
├── backend/               # Laravel 12 API (app/, routes/, tests/, ai-engine/)
├── frontend/              # React 19 console + public form + offline PWA /m
├── mesh/                  # protocol: sdk/, server/ (relay), demo/, android/ (APK)
├── desktop/               # Neutralino offline /m binary
└── compose.yaml + start.sh / stop.sh · CI: backend·frontend·relay·android·desktop·ai-engine
```

## 9. Tech stack

Laravel 12 · PHP 8.3 · Sanctum · spatie-permission · React 19 · TypeScript · Tailwind v4 ·
React Router 7 · Leaflet · Recharts · FastAPI · PyNaCl · Postgres 16 · Ollama (llama3.2:3b) ·
libsodium (sealed boxes + Ed25519) · Kotlin + Room + WorkManager · Neutralino · Docker Compose.

## 10. Community mesh (offline reporting)

A report hops phone to phone (QR, Nearby, BLE GATT) until one reaches the internet — or falls back
to SMS/USSD from any 2G phone. Signed bundles, spray-and-wait, E2E media, SQLite relay.
Full contract: [mesh/README.md](mesh/README.md).

## 11. Quickstart

```bash
git clone https://github.com/BrondonJores/WASH-SENTINEL && cd WASH-SENTINEL
./start.sh   # containers + key + migrate --force + seed + Ollama models
```

Console `http://localhost:5173` · API `http://localhost/api` · field `/m` · relay `:8001/health`.
Accounts (`password`): `admin@wash.cm`, `tech@wash.cm`, `directeur@ecole.cm`.
Mesh demo: `python3 mesh/demo/simulate_hops.py [--live]`. Production: [docs/DEPLOY.md](docs/DEPLOY.md).

## 12. API overview (`/api`, JSON-only)

Sanctum tokens + RBAC. Schools · reports · incidents (status/assign/override/logs) · agent
(chat, plans, epidemic-scan, proposals) · model/STT profiles · conversations · notifications ·
mesh (`bundles|sms|ussd`, `key`, `pending`, `stats`) · WhatsApp webhook + diagnostics.
Full table: [docs/HACKATHON.md §10](docs/HACKATHON.md).

## 13. Engineering you can audit 🔒

59 pytest (relay + crypto + frames + 3-relay chaos harness) · 56 mesh + 12 WhatsApp PHPUnit ·
Android unit tests + APK in CI · `tsc`, build, lint green · golden crypto vector across 3 languages ·
live `--live` probes. The one unproven claim (real Nearby/BLE radio) is labeled everywhere it matters.

## 14. Roadmap

- [x] Console + RBAC + AI copilot (chat, plans, epidemic scan, STT/vision)
- [x] WhatsApp pipeline + public form + notifications + relances
- [x] Mesh v1→v3 + field app v1/v2 + signatures/TOFU + USSD + hardened APK
- [x] Chaos harness, P0 hardening, jury docs aligned
- [ ] Two-phone field validation · production VPS deploy · operator USSD code
- [ ] LoRa feasibility · iOS native spike · adaptive spray

---

*WASH Sentinel — every school heard, with or without signal.* 💧🇨🇲
