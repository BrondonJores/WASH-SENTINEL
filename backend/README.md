# WASH Sentinel — Backend (Laravel API)

![Laravel](https://img.shields.io/badge/Laravel-12.x-FF2D20?logo=laravel)
![PHP](https://img.shields.io/badge/PHP-8.2%2B-777BB4?logo=php)
![Sanctum](https://img.shields.io/badge/Auth-Sanctum_tokens-38BDF8)
![PostgreSQL](https://img.shields.io/badge/DB-PostgreSQL_16-4169E1?logo=postgresql)
![Tests](https://img.shields.io/badge/Tests-PHPUnit_11-6DB33F)
![License](https://img.shields.io/badge/License-MIT-green)

> **Pitch.** This Laravel 12 API is the operational core of WASH Sentinel: it ingests
> water/sanitation failure reports from Cameroonian schools over **5 channels**
> (web, WhatsApp voice, SMS, USSD, offline mesh bundles), triages them with an
> AI engine (Ollama LLM + STT), deduplicates them against open incidents, scores
> their priority, notifies admins of critical cases, and drives the full
> repair lifecycle — assignment, status tracking, maintenance logs, dormant-case
> follow-ups (*relances*) — under Spatie RBAC with Sanctum token auth.

---

## 1. Stack (exact versions)

| Layer | Package | Version |
|---|---|---|
| Framework | `laravel/framework` | `^12.0` (lock: v12.70.2) |
| PHP | `php` | `^8.2` (compose image: PHP 8.3 FPM) |
| Auth | `laravel/sanctum` | `^4.0` (lock: v4.3.3) |
| RBAC | `spatie/laravel-permission` | `^8.3` (lock: 8.3.2) |
| Dev tools | `laravel/tinker`, `laravel/pail`, `laravel/sail`, `laravel/pint` | see `composer.json` |
| Tests | `phpunit/phpunit` | `^11.5.50` |
| Database | PostgreSQL 16 (`postgres:16-alpine` in compose) | SQLite `:memory:` in tests |
| Queue | `database` driver (`jobs` table) | `sync` in tests |
| AI engine | sibling FastAPI service (`ai-engine/`) + Ollama | `llama3.2:3b` default |

Sources: `composer.json:8-23`, `composer.lock` (framework/sanctum/permission),
`compose.yaml:30-55`, `phpunit.xml:29-38`.

---

## 2. Setup

### 2a. Full stack via Docker Compose (recommended)

```bash
# From the repo root:
docker compose up --build
```

Services started (`compose.yaml`): `app` (PHP 8.3 FPM + Nginx),
`queue` (runs `php artisan queue:work --sleep=3 --tries=3 --timeout=120`),
`pgsql` (PostgreSQL 16), `ai-engine` (FastAPI), `ollama`, mesh server, frontend.
Then, inside the app container:

```bash
php artisan migrate --force
php artisan db:seed   # roles + AI profiles + demo data (see §11)
```

### 2b. Standalone (local PHP)

```bash
cd backend
composer setup        # install + .env + key + migrate + npm build
php artisan db:seed
php artisan serve                              # API on http://localhost:8000
php artisan queue:work --sleep=3 --tries=3     # WhatsApp async worker
```

Prerequisites: PHP ^8.2 with `sqlite`/`pgsql` extensions, Composer, Node 22.
Default `.env` targets `DB_CONNECTION=pgsql`, `DB_HOST=pgsql`
(`.env.example:23-28`); for standalone without Postgres, set
`DB_CONNECTION=sqlite` and `DB_DATABASE=/absolute/path/database.sqlite`.

Health checks: `GET /api/v1/wash/overview` (public) and
`GET /api/v1/whatsapp/diagnostics` (config status, no secrets leaked).

---

## 3. Composer scripts

| Script | Command | Effect |
|---|---|---|
| `setup` | `composer install` + copy `.env` + `key:generate` + `migrate --force` + `npm install/build` | one-shot bootstrap |
| `dev` | concurrently: `serve` + `queue:listen --tries=1` + `pail` + `npm run dev` | all-in-one dev loop |
| `test` | `config:clear` + `artisan test` | full PHPUnit suite |

Source: `composer.json:36-52`.

---

## 4. Models (all 15)

| Model | Role | Key fields | Relations |
|---|---|---|---|
| `School` | A school site (unit of monitoring) | `name`, `code` (unique), `district` (indexed), `default_language` (`fr`/`en`/`dua_Latn`), geo, `student_count`, `female_students`, `equipment_type`, `installation_year`, `estimated_replacement_cost`, `contact_phone` | `incidents`, `openIncidents` (excl. resolved/closed), `reports`, `contacts`, `maintenanceLogs` |
| `Incident` | One deduplicated failure case; auto `reference_code` on create (`booted`) | `category` enum (5), `issue_type` enum (7), `status` enum (6), `urgency` enum (4), `health_hazard` enum (4), `priority_score`, `affected_students`, `ai_summary`, `ai_tags`, `assigned_to_user_id`, `resolved_at` | `school`, `reports`, `aiAnalyses`, `maintenanceLogs`, `assignee` (User); scope `open()` |
| `Report` | One raw incoming signal (always kept, even duplicates) | `channel` (voice/text/whatsapp/sms/ussd/mesh…), `source` (web/mesh…), `raw_content`, `audio_path`, `photo_path`, `is_duplicate`, `duplicate_of_incident_id`, `duplicate_similarity_score`, `raw_ai_extraction` | `incident`, `school`, `reporter`, `duplicateOf`, `aiAnalyses` |
| `User` | Staff accounts (Sanctum + Spatie roles) | `name`, `email`, `password` (hidden) | `assignedIncidents`, `reports` (as reporter) |
| `MaintenanceLog` | One repair intervention (cost history) | `cost_amount`, `currency` (XAF), `repaired_at`, `days_without_service`, `notes`, `performed_by` | `incident`, `school`, `technician` (User) |
| `AiAnalysis` | Audit row for every AI call (input/output payloads) | `analysis_type`, `input_payload`, `output_payload`, `model_used`, `confidence`, `processing_ms` | `incident`, `report` |
| `AiModelProfile` | Switchable LLM provider configs (API key encrypted, masked accessor) | `name`, `provider` (ollama/openai_compatible…), `base_url`, `model`, `vision_model`, `embed_model`, `api_key`, `timeout`, `is_active`, `is_default` | `active()` scope helper; `llmHeaders()`, `testPayload()` |
| `AiSttProfile` | Switchable speech-to-text configs | `name`, `driver`, `base_url`, `model`, `tokens_path`, `api_key`, `default_language`, `threads`, `timeout`, `is_active`, `is_default` | `active()` helper; `sttHeaders()`, `testPayload()` |
| `SchoolContact` | Verified phone directory (WhatsApp/SMS matching) | `phone` (normalized via `normalizePhone()`), `name`, `role`, `is_verified` | `school` |
| `MeshBundle` | One offline mesh packet (DTN-style: hops, custody, fragments, sealed E2E) | `bundle_id`, `bundle_group`, `origin_node_id`, `channel`, `message`, `payload`, `hop_count`/`max_hops`, `status`, `report_id`, `expires_at`, `delivered_at`, `destination_eid`, `lifetime_seconds`, `copies_remaining`, `fragment_offset`/`fragment_total`, `custody_requested`, `priority`, `signature`, `node_pubkey`, `sealed_payload`, `sealed_alg` | `school`, `report`; `isExpired()` |
| `MeshNodeKey` | Trust-on-first-use registry of node public keys | `origin_node_id`, `node_pubkey`, `first_seen_at`, `last_changed_at` | — |
| `AgentProposal` | Pending agent action awaiting human Oui/Non vote | `user_id`, `action`, `payload` (array), `status` (pending/confirmed/cancelled), `expires_at` | `user`; `isExpired()` |
| `Project` | Conversation folder (copilot library) | `user_id`, `name` | `user`, `conversations` |
| `Conversation` | One copilot thread | `user_id`, `project_id`, `title` | `user`, `project`, `messages` (ordered by `id` — stable across replace-all) |
| `Message` | One chat turn with tool/cards payloads | `role`, `content`, `tools`/`cards`/`follow_ups` (arrays), `model`, `said_at` | `conversation` |

Sources: `app/Models/*.php` (`$fillable` + relation methods),
migrations `2026_10_28_220600` (schools), `2026_10_28_220601` (incidents enums).

---

## 5. Controllers (all 16)

| Controller | Role | Actions |
|---|---|---|
| `AuthController` | Sanctum token issue/revoke | `token` (validate email+password → plain-text token), `destroy` (revoke current token) |
| `WashSchoolController` | School directory | `index` (filters: district/search), `show` (with open incidents + history), `store` (permission `manage schools`) |
| `WashReportController` | Report intake | `index` (filters: school/channel/duplicate), `store` (→ `IncidentTriageService::ingest`, throttle 60/min), `show` |
| `WashIncidentController` | Incident lifecycle | `index` (filters: status/urgency/district/search), `overview` (public KPI dashboard), `show` (+ AI repair plan), `updateStatus`, `assign`, `overridePriority`, `storeMaintenanceLog`, `assignableUsers`, `relance` (GET list / POST trigger dormants) |
| `WashAgentController` | AI copilot proxy | `copilotChat`, `converse` (agentic loop + proposal votes, throttle 30/min), `dispatchPlan` (equity), `epidemicScan`, `synthesize` (TTS), `transcribe` (STT, throttle 30/min), `replaceVsRepair` |
| `WashAgentProposalController` | Human-in-the-loop votes | `confirm`, `cancel` (auth + throttle 30/min) |
| `WashProjectController` | Copilot library folders | `index`, `store`, `update`, `destroy` (owner-scoped) |
| `WashConversationController` | Copilot threads | `library` (projects + conversations tree), `store`, `update`, `replaceMessages` (PUT full replace), `destroy` |
| `WashNotificationController` | In-app notifications | `index`, `read`, `readAll` (auth; critical-incident + relance alerts) |
| `WashMeshController` | Offline mesh ingestion | `store` (bundle → triage, throttle 60/min), `pending` (downlink queue), `show`, `stats`, `publicKey` (E2E box key) |
| `WashSmsController` | SMSSync gateway intake | `store` (secret + allowlist + quota → parse → triage, throttle 60/min) |
| `WashUssdController` | Menu-based USSD intake | `handle` (POST session walk), `probe` (GET diagnostics) |
| `WashWhatsAppController` | Meta Cloud API webhook | `verify` (GET handshake), `receive` (→ queue job, throttle 60/min), `diagnostics` |
| `Admin/WashAiAnalysisController` | AI audit log | `index` (paginated analyses; `manage ai settings`) |
| `Admin/WashModelProfileController` | LLM provider admin | full resource + `activate`, `test` (live provider check), `providerTypes` |
| `Admin/WashSttProfileController` | STT provider admin | full resource + `activate`, `test`, `sttTypes` |

Sources: `app/Http/Controllers/Api/*.php`, `Api/Admin/*.php`, `routes/api.php`.

---

## 6. Complete API table

Base URL: `/api`. All `v1/wash` auth routes need `Authorization: Bearer <token>`.

### 6a. Auth (`v1/auth`)

| Method | Path | Auth | Permission | Usage |
|---|---|---|---|---|
| POST | `/v1/auth/token` | no (throttle 10/min) | — | login with email+password → Sanctum token |
| DELETE | `/v1/auth/token` | Sanctum | — | logout (revoke current token) |
| GET | `/user` | Sanctum | — | current user (Laravel default) |

### 6b. WASH core — public reads

| Method | Path | Auth | Permission | Usage |
|---|---|---|---|---|
| GET | `/v1/wash/schools` | no | — | list schools (`?district=`, `?search=`) |
| GET | `/v1/wash/schools/{school}` | no | — | school detail + open incidents + maintenance history |
| GET | `/v1/wash/reports` | no | — | list reports (filters) |
| POST | `/v1/wash/reports` | no (throttle 60/min) | — | submit report (text/voice/photo) → AI triage |
| GET | `/v1/wash/reports/{report}` | no | — | report detail |
| GET | `/v1/wash/overview` | no | — | KPI dashboard (counts by status/urgency/district) |
| GET | `/v1/wash/incidents` | no | — | list incidents (filters: status/urgency/district/search) |
| GET | `/v1/wash/incidents/{incident}` | no | — | incident detail + AI repair plan |

### 6c. WASH agent — public AI endpoints

| Method | Path | Auth | Permission | Usage |
|---|---|---|---|---|
| POST | `/v1/wash/agent/chat` | no | — | decision-copilot Q&A over district data |
| POST | `/v1/wash/agent/converse` | no (throttle 30/min) | — | agentic loop (tools + proposal drafting) |
| POST | `/v1/wash/agent/dispatch-plan` | no | — | equity dispatch plan for a district |
| POST | `/v1/wash/agent/epidemic-scan` | no | — | cholera/epidemic risk scan for a district |
| POST | `/v1/wash/agent/synthesize` | no | — | TTS synthesis (Piper voice) |
| POST | `/v1/wash/agent/transcribe` | no (throttle 30/min) | — | STT transcription of uploaded audio |
| GET | `/v1/wash/agent/schools/{school}/replace-vs-repair` | no | — | replace-vs-repair economic analysis |

### 6d. WASH — authenticated writes

| Method | Path | Auth | Permission | Usage |
|---|---|---|---|---|
| POST | `/v1/wash/schools` | Sanctum | `manage schools` | create school |
| PATCH | `/v1/wash/incidents/{incident}/status` | Sanctum | `update incident status` | move status (reported→…→resolved/closed) |
| POST | `/v1/wash/incidents/{incident}/assign` | Sanctum | `assign incidents` | assign technician |
| POST | `/v1/wash/incidents/{incident}/override-priority` | Sanctum | `override ai priority` | human override of AI priority score |
| POST | `/v1/wash/incidents/{incident}/maintenance-logs` | Sanctum | `update incident status` | log a repair (cost, downtime) |
| GET | `/v1/wash/assignable-users` | Sanctum | `assign incidents` | staff list for assignment picker |
| GET | `/v1/wash/relances/dormants` | Sanctum | `view all incidents` | dormant incidents (default 7+ days idle) |
| POST | `/v1/wash/relances/dormants` | Sanctum | `update incident status` | trigger relance notifications |
| POST | `/v1/wash/agent/proposals/{proposal}/confirm` | Sanctum (throttle 30/min) | — (owner) | approve pending agent action |
| POST | `/v1/wash/agent/proposals/{proposal}/cancel` | Sanctum (throttle 30/min) | — (owner) | reject pending agent action |
| GET | `/v1/wash/library` | Sanctum | — (owner) | copilot library tree |
| GET/POST | `/v1/wash/projects` | Sanctum | — (owner) | list / create project folder |
| PATCH/DELETE | `/v1/wash/projects/{project}` | Sanctum | — (owner) | rename / delete folder |
| POST | `/v1/wash/conversations` | Sanctum | — (owner) | create thread |
| PATCH/DELETE | `/v1/wash/conversations/{conversation}` | Sanctum | — (owner) | rename / delete thread |
| PUT | `/v1/wash/conversations/{conversation}/messages` | Sanctum | — (owner) | replace-all messages |

### 6e. Admin (`v1/admin`, all Sanctum + `manage ai settings`)

| Method | Path | Usage |
|---|---|---|
| GET | `/v1/admin/ai-analyses` | paginated AI audit log |
| GET | `/v1/admin/provider-types` | LLM provider types supported by ai-engine |
| GET/POST | `/v1/admin/model-profiles` | list / create LLM profile |
| GET/PATCH/DELETE | `/v1/admin/model-profiles/{modelProfile}` | show / update / delete |
| POST | `/v1/admin/model-profiles/{modelProfile}/activate` | set active LLM profile |
| POST | `/v1/admin/model-profiles/{modelProfile}/test` | live provider connectivity test |
| GET | `/v1/admin/stt-types` | STT driver types |
| GET/POST | `/v1/admin/stt-profiles` | list / create STT profile |
| GET/PATCH/DELETE | `/v1/admin/stt-profiles/{sttProfile}` | show / update / delete |
| POST | `/v1/admin/stt-profiles/{sttProfile}/activate` | set active STT profile |
| POST | `/v1/admin/stt-profiles/{sttProfile}/test` | live STT test |

### 6f. Notifications, mesh, WhatsApp

| Method | Path | Auth | Usage |
|---|---|---|---|
| GET | `/v1/notifications` | Sanctum | list own notifications |
| POST | `/v1/notifications/read-all` | Sanctum | mark all read |
| POST | `/v1/notifications/{notification}/read` | Sanctum | mark one read |
| POST | `/v1/mesh/bundles` | optional `X-Mesh-Key` (throttle 60/min) | ingest offline bundle → triage |
| GET | `/v1/mesh/bundles/pending` | no | downlink queue for nodes |
| GET | `/v1/mesh/bundles/{bundleId}` | no | bundle status |
| GET | `/v1/mesh/stats` | no | mesh ingestion stats |
| GET | `/v1/mesh/key` | no | server E2E public key (sealed box) |
| POST | `/v1/mesh/sms` | shared secret (throttle 60/min) | SMSSync gateway intake |
| POST | `/v1/mesh/ussd` | no (throttle 60/min) | USSD session handler |
| GET | `/v1/mesh/ussd` | no (throttle 60/min) | USSD probe/diagnostics |
| GET | `/v1/whatsapp/webhook` | verify token | Meta handshake (hub.challenge) |
| POST | `/v1/whatsapp/webhook` | HMAC signature (throttle 60/min) | incoming message → queue job |
| GET | `/v1/whatsapp/diagnostics` | no | config status (no secrets) |

Source: `routes/api.php:1-104` (every route above maps 1:1).

---

## 7. Services (all 10)

| Service | Role |
|---|---|
| `IncidentTriageService` (`IncidentTriage`) | Central intake pipeline: `ingest(school, channel, message, audio, photo, reporter, source, overrides)` → STT/transcribe → LLM extract → duplicate check (threshold 0.80) → create Incident+Report+AiAnalysis → notify on critical; `createManualIncident()` for staff-created cases |
| `AgentProposalService` | Human-in-the-loop: `draft(user, action, slots)` creates expiring proposal, `confirm()` executes the side effect (status/assign/log), `cancel()` voids; expired proposals throw guidance errors with redraft prompt |
| `WashAiEngineService` (`AiEngineClient`) | Typed HTTP client for all 20 ai-engine endpoints: `triage`, `extract`, `checkDuplicates`, `analyzeImage`, `repairPlan`, `epidemicScan`, `copilotChat`, `replaceVsRepair`, `agentChat`, `dispatchPlan`, `synthesize`, `transcribe`, `health`, `providerTypes`/`testProfile`, `sttTypes`/`testSttProfile`; injects active profile headers |
| `WashWhatsAppService` | Voice-channel orchestrator: `handlePayload()` (voice note → STT → triage → recap text + Oui/Non buttons + TTS note), `verifySignature()`, `isDuplicateDelivery()`, `isWithinFreeformWindow()`, `sendFollowup()` (template outside 24h window) |
| `MetaWhatsAppService` (`WhatsAppClient`) | Low-level Graph API v21 wrapper: `parseWebhook`, `downloadMedia`, `sendText`, `sendInteractiveButtons`, `uploadMedia`, `sendAudio`, `sendTemplate`; `simulator` mode for local dev (no Meta calls) |
| `WashRelanceService` | Dormant-case follow-ups: `dormants(days=7)` (open statuses idle ≥ N days), `relancer()` / `relancerDormants()` send `WashRelanceNotification` |
| `MeshSmsParser` | Parses compact SMS/USSD syntax (`parse`), school-code lookup (`findSchoolByCode`), FR acknowledgements (`acknowledge`), USSD menu mapping (`ussdChoiceToType`, `buildUssdMessage`) |
| `MeshMediaAssembler` | Reassembles fragmented photo/audio bundles: `tryAssemble(groupId)` returns the complete `MeshBundle` once all fragments arrive |
| `MeshSeal` | libsodium sealed-box E2E: `publicKeyB64()` (published at `GET /mesh/key`), `open()` decrypts client-sealed payloads; empty `MESH_SEAL_SECRET` = plaintext fallback with warning |
| `MeshSignature` | Ed25519 bundle signing: `generateKeypair`, `sign`/`signBundle`, `verify`, `canonicalString`/`canonicalBytes`; trust-on-first-use via `MeshNodeKey` |

Sources: `app/Services/*.php`, `app/Contracts/` (interfaces), `config/services.php:43-59`.

---

## 8. Jobs + queue

| Item | Detail |
|---|---|
| Job | `ProcessWhatsAppMessage` (`app/Jobs/ProcessWhatsAppMessage.php:9`) — `ShouldQueue`, carries the webhook payload array, delegates to `WashWhatsAppService::handlePayload()` |
| Dispatch | `WashWhatsAppController::receive` dispatches synchronously-returning `200 OK` to Meta, heavy work async |
| Driver | `database` (`QUEUE_CONNECTION`, `config/queue.php:16`), `jobs` table, `retry_after` 90s |
| Worker | `php artisan queue:work --sleep=3 --tries=3 --timeout=120` (`compose.yaml:32`); dev uses `queue:listen --tries=1` (`composer.json:47`) |
| Failures | `failed_jobs` table (`database-uuids` driver, `config/queue.php:123-127`) |
| Tests | `QUEUE_CONNECTION=sync` in `phpunit.xml:35` — jobs run inline |

---

## 9. Artisan commands

| Command | File | Usage |
|---|---|---|
| `php artisan mesh:key-generate` | `app/Console/Commands/MeshKeyGenerate.php:9` | generates the server libsodium E2E keypair; prints base64 secret → set as `MESH_SEAL_SECRET` |
| `php artisan wash:whatsapp:preflight` | `app/Console/Commands/WhatsappPreflightCommand.php:19` | pre-live checklist: `WHATSAPP_ENABLED`, token, phone ID, verify token (≥16 chars), `APP_SECRET` (HMAC), 24h-template config; fails closed with actionable errors |

---

## 10. RBAC

**Permissions (12)** — `database/seeders/WashRoleSeeder.php:15-28`:
`create reports`, `view own school reports`, `view all incidents`,
`edit incidents`, `assign incidents`, `update incident status`,
`override ai priority`, `use ai assistant`, `view ai analytics`,
`manage schools`, `manage users`, `manage ai settings`.

**Role × capability matrix:**

| Capability | `school_reporter` | `maintenance_agent` | `wash_admin` |
|---|---|---|---|
| create reports | ✅ | — | ✅ |
| view own school reports | ✅ | — | ✅ |
| view all incidents | — | ✅ | ✅ |
| edit incidents | — | ✅ | ✅ |
| assign incidents | — | — | ✅ |
| update incident status | — | ✅ | ✅ |
| override ai priority | — | — | ✅ |
| use ai assistant | ✅ | ✅ | ✅ |
| view ai analytics | — | — | ✅ |
| manage schools | — | — | ✅ |
| manage users | — | — | ✅ |
| manage ai settings | — | — | ✅ |

Enforcement: `permission:` route middleware (`routes/api.php:47-55,66`) via
Spatie `HasRoles` on `User` (`app/Models/User.php:11`).

---

## 11. Seed data

Run: `php artisan db:seed` → `AiModelProfileSeeder`, `AiSttProfileSeeder`,
`WashRoleSeeder`, `WashDemoSeeder`, plus `test@example.com`
(`DatabaseSeeder.php:21-27`).

**Accounts** (all password `password`, `WashDemoSeeder.php:18-32`):

| Email | Name | Role |
|---|---|---|
| `admin@wash.cm` | Amina Ngo Bell | `wash_admin` |
| `tech@wash.cm` | Jean Fotso | `maintenance_agent` |
| `directeur@ecole.cm` | Clarisse Eko | `school_reporter` |

**8 schools, 3 districts** (`WashDemoSeeder.php:256-324`): Wouri urban
(Bonanjo `DOU-BON-001`, Libermann, Bali), Mvila rural (Ngok, Nkol —
Duala `dua_Latn` default), Sanaga-Maritime (Édéa, Pouuma, Nyo).
**9 incidents** spanning all 5 categories and all urgencies, incl. a 31-day
equity-mirror critical case (Pouuma) vs. triaged urban Bonanjo;
**6+ reports** in FR/EN/Camfranglais; **5 verified school contacts**;
**4 maintenance logs** in XAF; LLM profiles (Ollama `llama3.2:3b` active +
OpenAI-compatible + gemma fallbacks) and STT profiles preseeded.

---

## 12. Config & environment

### WASH-specific vars (`.env.example:67-99`)

| Variable | Default | Effect |
|---|---|---|
| `AI_ENGINE_URL` | `http://ai-engine:8000` | FastAPI base URL (`services.ai_engine.url`) |
| `AI_ENGINE_TIMEOUT` | `120` | HTTP timeout (s) for AI calls |
| `OLLAMA_URL` | `http://ollama:11434` | Ollama server (used by ai-engine) |
| `OLLAMA_MODEL` | `llama3.2:3b` | default LLM |
| `OLLAMA_VISION_MODEL` | `llama3.2-vision:11b` | image analysis model |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | duplicate-detection embeddings |
| `WHATSAPP_ENABLED` | `true` | `false` → webhook answers 503 |
| `WHATSAPP_BASE_URL` | `https://graph.facebook.com/v21.0` | Graph API version pin |
| `WHATSAPP_PHONE_NUMBER_ID` / `WHATSAPP_WABA_ID` | — (required live) | sender number / business account |
| `WHATSAPP_TOKEN` (`WHATSAPP_ACCESS_TOKEN` legacy) | — (required live) | Cloud API token |
| `WHATSAPP_VERIFY_TOKEN` | `sentinel-webhook-token` | GET handshake secret (≥16 chars) |
| `WHATSAPP_APP_SECRET` | — (required live) | HMAC `X-Hub-Signature-256` verification |
| `WHATSAPP_SIMULATOR` | `false` | dev mode: no Meta calls, no signature |
| `WHATSAPP_VOICE_CONFIRMATION` / `WHATSAPP_VOICE_NOTE` | `true`/`true` | recap + Oui/Non buttons + TTS note after triage |
| `WHATSAPP_TTS_VOICE` | `fr_FR-upmc-medium` | Piper voice (ai-engine side) |
| `WHATSAPP_CONFIRMATION_TEMPLATE` / `..._LANGUAGE` | `wash_confirmation`/`fr` | approved template outside the 24h free-form window (else Meta error 131047) |
| `WHATSAPP_PENDING_TTL` | `86400` | Oui/Non confirmation cache lifetime (s) |
| `WHATSAPP_MAX_MEDIA_BYTES` | `10485760` (10 MB) | inbound media cap; over → guided FR reply, no storage |
| `MESH_SEAL_SECRET` | — (empty) | base64 32-byte server box key; empty = E2E off, plaintext fallback |
| `MESH_INGEST_KEY` | — (empty) | optional `X-Mesh-Key` gate; empty = public ingest + throttle/quotas |
| `MESH_SMS_SECRET` | `change-moi-passerelle-sms` | SMSSync shared secret — **fail-closed if empty** |
| `MESH_SMS_ALLOWLIST` | — (empty) | optional comma-separated sender allowlist |
| `MESH_DAILY_CAP_PER_ORIGIN` | `500` | bundles/day per origin node |
| `MESH_SMS_QUOTA_PER_SENDER` | `10` | SMS/day per sender |

Infra vars: `DB_*` (pgsql, `DB_HOST=pgsql`), `QUEUE_CONNECTION=database`,
`CACHE_STORE=database`, `SESSION_DRIVER=database`, `MAIL_MAILER=log`,
`APP_LOCALE=fr` (`.env.example:1-65`).

---

## 13. AI engine (`ai-engine/`, FastAPI)

**Role:** stateless Python microservice — all LLM/STT/vision work lives here so
the Laravel app stays a thin orchestrator. Default provider: local Ollama
(`llama3.2:3b`, vision `11b`, `nomic-embed-text`); OpenAI-compatible providers
supported via admin profiles. STT: sherpa-onnx + Piper TTS
(`ai-engine/requirements.txt`).

**Endpoints** (`ai-engine/app/main.py`):

| Method | Path | Used by |
|---|---|---|
| GET | `/health` | `WashAiEngineService::health()` |
| POST | `/v1/wash/triage` | `triage()` — full report triage |
| POST | `/v1/wash/extract` | `extract()` — structured slot extraction |
| POST | `/v1/wash/check-duplicates` | `checkDuplicates()` (threshold 0.80) |
| POST | `/v1/wash/analyze-image` | `analyzeImage()` — photo damage analysis |
| POST | `/v1/wash/generate-repair-plan` | `repairPlan()` — incident detail |
| POST | `/v1/wash/detect-epidemic-risk` | `epidemicScan()` |
| POST | `/v1/wash/equity/dispatch-plan` | `dispatchPlan()` |
| POST | `/v1/wash/copilot/chat` | `copilotChat()` |
| POST | `/v1/wash/copilot/replace-vs-repair` | `replaceVsRepair()` |
| POST | `/v1/voice/transcribe` | `transcribe()` — STT |
| POST | `/v1/voice/synthesize` | `synthesize()` — Piper TTS |
| POST | `/v1/agent/chat` | `agentChat()` — agentic loop |
| POST | `/v1/wash/rag/ask` | RAG Q&A over WASH docs |
| POST | `/v1/wash/recurrence-watch` | recurrence detection |
| GET | `/v1/admin/provider-types` | LLM provider catalog |
| POST | `/v1/admin/test-provider` | live LLM test |
| POST | `/v1/admin/warmup` | model warmup |
| GET | `/v1/admin/stt-types` | STT driver catalog |
| POST | `/v1/admin/test-stt` | live STT test |
| GET | `/v1/admin/tts-types` | TTS voice catalog |
| GET | `/v1/admin/ai-metrics` | AI usage metrics |

Key modules: `agent_loop.py` (tool loop), `agent_tools.py` (data tools),
`guidance.py` + `guided_voice.py` (FR/EN/Duala guided flows), `extractor.py`,
`duplicate_detector.py`, `epidemic_detector.py`, `equity_dispatcher.py`,
`repair_advisor.py`, `image_analyzer.py`, `voice_service.py`, `providers.py`,
`stt_providers.py`, `rag_store.py`.

---

## 14. Tests

Run: `composer test` (or `php artisan test`). Env: SQLite `:memory:`,
`sync` queue, `array` cache/session (`phpunit.xml:24-38`).
**24 suites, 169 test methods:**

| Suite | Tests | Covers |
|---|---|---|
| `WashAgentProposalTest` | 15 | proposal draft/confirm/cancel/expiry |
| `WashMeshTest` | 14 | mesh bundle ingest/status/quotas |
| `WashWhatsAppTest` | 14 | webhook verify/receive/triage flow |
| `WashCrudFiltersTest` | 13 | index filters + pagination |
| `WashUssdTest` | 12 | USSD menu walks |
| `WashWhatsAppGuidanceTest` | 11 | guided FR/EN/Duala replies |
| `MeshSignatureTest` | 10 | Ed25519 sign/verify/canonical |
| `WashLibraryTest` | 9 | projects/conversations/messages |
| `WashRelancesTest` | 7 | dormant detection + relance |
| `WashAgentGuidanceTest` | 6 | copilot guidance flows |
| `WashMeshMediaTest` | 6 | fragment reassembly |
| `AiSttProfileTest` | 6 | STT profile CRUD/activate |
| `AiModelProfileTest` | 5 | LLM profile CRUD/activate |
| `WashSmsTest` | 5 | SMS secret/allowlist/parse |
| `WhatsappPreflightTest` | 5 | preflight checks |
| `AuthTest` | 4 | token issue/revoke |
| `WashAgentLoopTest` | 4 | agentic loop |
| `WashCrudTest` | 4 | core CRUD |
| `MeshNodeKeyTest` | 4 | TOFU node keys |
| `WashWhatsAppDiagnosticsTest` | 4 | diagnostics endpoint |
| `CriticalIncidentNotificationTest` | 2 | critical alerts |
| `WashOverviewTest` | 1 | overview KPIs |
| `WashTriageLanguageTest` | 1 | triage language handling |
| `ExampleTest` | 1 | framework sanity |

Source: `tests/Feature/*.php` (method counts via `public function test`).

---

## 15. Security

- **Auth:** Sanctum personal access tokens (`AuthController::token`,
  throttle 10/min); password hashed with bcrypt (12 rounds, 4 in tests).
- **RBAC:** Spatie permissions on every mutating route (§10); owner-scoping on
  library/proposal resources.
- **Throttles:** reports/mesh/sms/ussd/webhook 60/min; agent converse/transcribe
  + proposal votes 30/min; login 10/min (`routes/api.php`).
- **WhatsApp:** HMAC `X-Hub-Signature-256` required in live mode, verify-token
  handshake, duplicate-delivery guard, 10 MB media cap, simulator banned in
  production (`config/whatsapp.php`, `MetaWhatsAppService::verifySignature`).
- **Mesh/SMS:** optional ingest key, mandatory SMS shared secret (fail-closed
  when empty), sender allowlist, per-origin daily caps and per-sender quotas
  (`config/services.php:43-59`).
- **E2E option:** libsodium sealed-box (`MeshSeal`) + Ed25519 bundle signatures
  with TOFU node registry (`MeshNodeKey`).
- **Validation:** `$request->validate()` on every write endpoint; API keys
  encrypted at rest with masked accessors (`AiModelProfile`/`AiSttProfile`).
- **Audit:** every AI call persisted to `ai_analyses` (input/output/model/
  latency); admin-only read access.

---

## 16. Honest limits

- Public read endpoints (schools/incidents/overview) have **no auth** — fine for
  a hackathon demo, needs scoping before production.
- `WHATSAPP_SIMULATOR=true` disables signature checks — dev-only by design.
- Empty `MESH_SEAL_SECRET`/`MESH_INGEST_KEY` = plaintext/public mesh ingest.
- AI quality depends on local Ollama models (`llama3.2:3b` default); no
  offline fallback if ai-engine is down (Laravel returns 5xx guidance errors).
- Queue is single-worker `database` driver; no horizontal scaling configured.
- French-first UX (Duala/English supported in guided flows, FR default locale).

---

## 17. Folder structure

```
backend/
├── app/
│   ├── Contracts/          # AiEngineClient, IncidentTriage, WhatsAppClient interfaces
│   ├── Http/Controllers/Api/ (+ Admin/)  # 16 controllers (§5)
│   ├── Services/           # 10 services (§7)
│   ├── Jobs/               # ProcessWhatsAppMessage
│   ├── Console/Commands/   # mesh:key-generate, wash:whatsapp:preflight
│   ├── Models/             # 15 models (§4)
│   └── Notifications/      # CriticalIncidentNotification, WashRelanceNotification
├── ai-engine/              # FastAPI microservice (§13)
├── config/                 # services, whatsapp, queue, sanctum, permission…
├── database/
│   ├── migrations/         # 26 migrations (users, cache, jobs, schools, incidents,
│   │                       # reports, maintenance, ai_analyses, profiles ×2, permissions,
│   │                       # notifications, contacts, projects, conversations, messages,
│   │                       # mesh bundles + v11/sealed/group/pubkey/node-keys, said_at)
│   └── seeders/            # roles, AI profiles, demo data (§10–11)
├── routes/api.php          # every endpoint (§6)
├── tests/Feature/          # 24 suites (§14)
├── composer.json / .env.example / phpunit.xml
└── README.md               # this file
```


