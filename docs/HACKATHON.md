# WASH Sentinel — Complete Documentation

### The dashboardless AI guardian for school water & sanitation — online, on WhatsApp, and fully offline.

[![Stack](https://img.shields.io/badge/stack-Laravel%2012%20%7C%20React%2019%20%7C%20FastAPI-blue)]()
[![Tests](https://img.shields.io/badge/tests-59%20pytest%20%7C%2068%20PHPUnit%20mesh%2BWA-green)]()
[![Crypto](https://img.shields.io/badge/crypto-libsodium%20only-blue)]()
[![Offline](https://img.shields.io/badge/offline-mesh%20%7C%20SMS%20%7C%20USSD%20%7C%20QR-green)]()

> Meta Hackathon project — pilot for rural **Cameroon 🇨🇲**.
> Living docs: [mesh protocol](../mesh/README.md) · [demo script](DEMO_JURY.md) · [field install](INSTALL.md) ·
> [deploy](DEPLOY.md) · [relay ops](MESH_RUNBOOK.md) · [USSD](USSD.md) · [WhatsApp live](WHATSAPP_LIVE.md)

---

## 0. TL;DR (30-second jury pitch)

Schools report broken pumps and sanitation failures through **three doors**: an AI console (French, role-based),
WhatsApp (text + voice notes), and an **offline mesh** (phone-to-phone relay, QR, SMS, USSD) for villages without
coverage. Every report becomes a deduplicated, prioritized **incident** with an audit trail, assignment, maintenance
logs and follow-ups — no dashboard babysitting required.

---

## 1. Problem

- **Silent failures**: a broken pump can cut drinking water for 400 pupils for weeks before anyone with authority hears about it.
- **No connectivity**: remote schools have no data — web apps and WhatsApp are useless there.
- **Noisy channels**: reports arrive by calls, paper notes and word of mouth — duplicates, no priority, no follow-up.
- **No feedback loop**: reporters never learn what happened to their report, so they stop reporting.

## 2. Solution

One pipeline, three doors, one incident ledger:

| Door | User | Channel | Works offline |
|---|---|---|---|
| AI console `/` | admin, technician, director | web (FR) | no |
| Public form `/signaler` | anyone with a browser | web, no login | no |
| WhatsApp | school contacts | text + voice notes | no (needs Meta) |
| Mesh field app `/m` | directors, relay carriers | PWA/APK/desktop, QR | **yes** |
| SMS / USSD | any 2G phone | `WASH <CODE> <TYPE>` / `*123#` menus | **yes** |

Everything converges into `incidents`: deduped (text + semantic + photo-hash), scored (severity × exposure ×
recurrence), assigned, tracked, relanced when dormant. The AI proposes; humans dispose (every AI action needs
explicit confirmation, full audit trail).

## 3. Demo script (5 minutes, all local)

Prerequisites: `./start.sh`, then open `http://localhost:5173`.

| Min | Step | Expected |
|---|---|---|
| 0–1 | Login `admin@wash.cm` / `password` → console `/` | KPI cards, map, trend chart |
| 1–2 | `/signaler` (second window, no login) : pump report + photo | incident created, severity computed |
| 2–3 | WhatsApp simulator : send text fixture via `/api/v1/whatsapp/webhook` | incident with `source: whatsapp` |
| 3–4 | Airplane mode on `/m` : create report → QR → scan it from another tab | bundle forwarded, outbox states |
| 4–5 | `python3 mesh/demo/simulate_hops.py --live` + `/admin/mesh` | A→B→C hops visible, stats update |

Seeded accounts (password `password`): `admin@wash.cm` (wash_admin), `tech@wash.cm`
(maintenance_agent), `directeur@ecole.cm` (school_reporter). Seed: 4 incidents, Cameroonian schools, AI profiles.

## 4. Key features

**Console (role-based, FR):** overview KPIs + map + trends; incidents lifecycle
(`open → in_progress → resolved → closed`, validated transitions); reports inbox with AI analysis;
schools registry; maintenance logs per incident; dormant relaunch (dry-run safe); notifications;
journal (audit); settings (LLM/STT profiles); mesh monitor (`/admin/mesh`: stats, pending, bundles).

**AI copilot:** natural-language chat with tool calls (11 tools), plan dispatch with user confirmation,
epidemic-scan detector (deterministic thresholds), replace-vs-repair advisor, STT profiles with test,
model profiles with warmup; every proposal is confirm/cancel, never auto-applied.

**WhatsApp:** Meta webhook (verify + signed receive, 60/min), queued processing, text/voice/photo
triage into the same pipeline, registration reply for unknown numbers, simulator mode for dev,
secret-less diagnostics endpoint.

**Offline mesh:** signed bundles (Ed25519 + TOFU), spray-and-wait relay, QR/SMS/USSD transports,
E2E sealed media fragments, SQLite relay with retry+breaker uplink, installable PWA + desktop
binary + Android relay APK. Full contract: [mesh/README.md](../mesh/README.md).

## 5. Architecture

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

| Service | Container port | Role |
|---|---|---|
| laravel | 8080 → `:80` | API, triage, incidents, auth |
| queue | — | `queue:work` async jobs |
| pgsql | 5432 | data, `wash-pgsql` volume |
| ai-engine | 8000 | NLP/STT/vision helpers |
| ollama | 11434 | local LLM (+ cloud profiles) |
| mesh-relay | 8001 | store-and-forward + uplink |
| frontend | 5173 | Vite dev (prod: static build) |

## 6. Tech stack

| Layer | Choice | Why |
|---|---|---|
| API | Laravel 12, PHP 8.3, Sanctum, spatie-permission | RBAC, queues, ecosystem |
| Web | React 19, TS, Tailwind v4, Router 7, Leaflet, Recharts | console + offline PWA |
| Relay/AI | Python FastAPI, PyNaCl, httpx | light services, libsodium |
| Data | Postgres 16, SQLite (relay), localStorage (PWA) | durable at every layer |
| Crypto | libsodium only (sealed boxes, Ed25519) | zero home-made crypto |
| Mobile | Kotlin APK (Nearby+BLE+SMS+QR), Neutralino desktop | relay + field capture |
| Infra | Docker Compose, 7 services, 4 volumes | one-command start |

## 7. Repository map

```text
.
├── README.md              # main doc (FR) — console-focused
├── docs/                  # HACKATHON.md (this file) · DEMO_JURY.md · DEMO.md · INSTALL.md
│                          # DEPLOY.md · MESH_RUNBOOK.md · USSD.md · WHATSAPP_LIVE.md
├── backend/               # Laravel 12 API (app/, routes/, tests/, ai-engine/)
├── backend/ai-engine/     # Python NLP/STT/vision service
├── frontend/              # React 19 console + public form + offline PWA /m
├── mesh/                  # protocol: sdk/, server/ (relay), demo/, android/ (APK)
├── desktop/               # Neutralino wrapper (offline /m binary)
├── compose.yaml           # 7 services · start.sh / stop.sh
└── .github/workflows/ci.yml  # backend · frontend · relay · android · desktop · ai-engine
```

## 8. Getting started

**Prerequisites:** Docker + Compose plugin, 2 GB RAM (cloud-LLM profile) or ~8 GB (local Ollama),
ports 80/5173/5432/8000/8001/11434 free.

```bash
git clone https://github.com/BrondonJores/WASH-SENTINEL && cd WASH-SENTINEL
./start.sh        # containers + key + migrate --force + seed + Ollama models
```

Then: console `http://localhost:5173` (login, see §3) · API `http://localhost/api` ·
field app `http://localhost:5173/m` · relay `http://localhost:8001/health`.
Stop: `./stop.sh`. Production (VPS + HTTPS + checklists): [DEPLOY.md](DEPLOY.md).

First-time mesh demo (no hardware): `python3 mesh/demo/simulate_hops.py [--live] [--burst 50]`.

## 9. Usage guide

**Admin (console):** triage the reports inbox → confirm AI severity → assign to a technician →
track maintenance logs → close; relaunch dormant incidents; monitor `/admin/mesh` for offline traffic.

**Director online:** public form `/signaler` (no login) or WhatsApp message/voice note to the school
number → automatic incident + reply.

**Director offline:** PWA `/m` (install once, then airplane-proof): fill the form → file stored
locally → show the QR to any carrier (Android relay, taxi-moto phone, iPhone) → the bundle hops
until someone uploads. No smartphone? Text `WASH <CODE> <TYPE>` or dial the USSD menus from any 2G phone.

**Relay carrier (Android APK):** start the relay once (Foreground + boot persistence) → the phone
gossips Nearby, falls back to BLE, queues SMS gateway traffic, and uploads everything on signal.

## 10. API reference (`/api`, JSON-only)

Auth: `POST /api/token` (Sanctum), `DELETE /api/token`. RBAC via `spatie/laravel-permission`
(`manage schools`, `assign incidents`, `override ai priority`, …).

| Domain | Endpoints |
|---|---|
| Schools | `GET /v1/schools`, `GET /v1/schools/{id}`, `POST /v1/schools` |
| Reports | `GET /v1/reports[/{id}]`, `POST /v1/reports`, `GET /v1/ai-analyses` |
| Incidents | `GET /v1/incidents[/{id}]`, `PATCH /v1/incidents/{id}/status`, `POST …/assign|override-priority|maintenance-logs`, `GET /v1/overview` |
| Agent | `POST /v1/agent/chat|converse|dispatch-plan|epidemic-scan|synthesize|transcribe`, `POST /v1/agent/proposals/{id}/confirm|cancel`, `GET …/replace-vs-repair` |
| Profiles | `GET /v1/provider-types|stt-types`, model/STT profile `activate|test` |
| Social | conversations CRUD, library, notifications, relances dormants |
| Mesh | `POST /v1/mesh/bundles|sms|ussd`, `GET /v1/mesh/ussd|key|bundles/pending|bundles/{id}|stats` |
| WhatsApp | `GET|POST /v1/whatsapp/webhook`, `GET /v1/whatsapp/diagnostics` |

Relay (`:8001`, `X-Mesh-Key` iff configured): `GET /health|/metrics|/v1/stats`,
`POST /v1/store|fetch|sync|ack|uplink`, `WS /v1/ws/{node_id}`.

## 11. AI details (auditable, not magic)

- **Triage**: every report (text, voice transcript, photo tags) gets severity/type/school-match with
  sources shown; humans confirm before any incident mutation.
- **Dedup**: text similarity + semantic threshold + photo hash — mesh duplicates collapse by `bundle_id` first.
- **Voice**: STT profiles (local/cloud) with one-click test; voice notes become transcribed reports.
- **Vision**: photo tags feed severity (displayed, not silently fused).
- **Epidemic scan**: deterministic multi-school symptom clustering with documented thresholds.
- **Safety rails**: proposal confirm/cancel flow, validated status transitions, contradiction guard,
  full journal — the AI never writes silently.

## 12. Mesh protocol (summary)

Signed store-and-forward bundles (UUID dedup, `hops` loop protection, TTL 7 d, max 10 hops,
Binary Spray-and-Wait L=8) over QR / Nearby / BLE GATT / SMS / USSD; Ed25519 authenticity with
TOFU key memory; libsodium sealed boxes so relays never read content; encrypt-then-chunk media
with out-of-order reassembly; SQLite relay with retry + circuit-breaker uplink.
Full contract, threat model and honest limits: [mesh/README.md](../mesh/README.md).

## 13. Testing & QA

| Suite | Command | Count |
|---|---|---|
| Relay + frames + harness | `pytest mesh/server mesh/demo` | 59 |
| Laravel mesh (bundles, media, SMS, USSD, sig, TOFU) | `php artisan test --filter 'WashMesh\|WashSms\|WashUssd\|MeshSig\|MeshNodeKey'` | 56 |
| WhatsApp (webhook, triage, diagnostics) | `php artisan test --filter WashWhatsApp` | 12 |
| Android unit + APK | CI `testDebugUnitTest` + `assembleDebug` | 5 files |
| Frontend | `tsc -b`, `npm run build`, `npm run lint` | 0 errors |

Beyond unit tests: a **golden crypto vector** reproduced byte-for-byte in TS/Python/PHP with real
libsodium; a **3-relay chaos harness** (kill -9, TTL, duplicates) in CI; a **live probe**
(`--live`) against real HTTP; QR round-trips and offline-first PWA verified in the production bundle.

## 14. Security & privacy

- Webhook/USSD/SMS writes throttled (60/min); relay key optional but recommended in prod.
- Signatures verified at relay ingress and on direct upload; TOFU alerts on key change.
- Sealed boxes: relays and carriers never read report content; server opens with `MESH_SEAL_SECRET`.
- No PII in mesh bundles (no names/phone numbers); diagnostics endpoints expose booleans, never secrets.
- RBAC on all mutations; audit journal on AI actions; confirmed-fixes only (fail-closed secrets).

## 15. Pilot budget (indicative, Cameroon 2026)

| Item | Estimate |
|---|---|
| VPS 2–4 GB + domain + HTTPS | ~€6/mo + ~€10/yr |
| 2 relay Androids/zone (used) + solar | ~€60–100 one-off |
| Gateway data + reporter SMS | carrier rates, Mobile Money top-ups |
| USSD short code | operator quote required |

## 16. Roadmap

Done: console + RBAC + AI copilot (chat, plans, epidemic scan, STT/vision) · WhatsApp live pipeline ·
public form · mesh v1→v3 (relay, E2E, media, BLE) · field app v1/v2 (PWA, desktop, hardened APK) ·
signatures + TOFU + USSD · chaos harness · jury docs aligned.

Next: two-phone field validation (Nearby/BLE range + battery) · real operator USSD code ·
production VPS deploy · LoRa feasibility + ART check · iOS native spike · adaptive spray research.

## 17. Known limitations (read before the jury asks)

- Real Nearby/BLE radio never ran on hardware — the one unproven claim, labeled everywhere it matters.
- iOS can't background-relay (Apple); USSD code is fictional pending an operator contract.
- Offline covers **collection**; consolidation still needs the server reachable.
- Dev-first repo: `start.sh` targets local Docker; production needs [DEPLOY.md](DEPLOY.md).

---

*WASH Sentinel — every school heard, with or without signal.* 💧🇨🇲

