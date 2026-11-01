# WASH Sentinel — Frontend

[![React 19](https://img.shields.io/badge/React-19.3-teal)](https://react.dev)
[![Vite 8](https://img.shields.io/badge/Vite-8.3-purple)](https://vite.dev)
[![Tailwind v4](https://img.shields.io/badge/Tailwind-4.3-cyan)](https://tailwindcss.com)
[![TypeScript](https://img.shields.io/badge/TypeScript-7.0-blue)](https://www.typescriptlang.org)
[![PWA](https://img.shields.io/badge/PWA-installable-green)](https://web.dev/progressive-web-apps/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](../LICENSE)

Three apps in one bundle: the **Mission Control console** (AI chat + CRUD ops for the
WASH team), the **public report form** at `/signaler` (no account, citizen reporting),
and the **offline-first field PWA** at `/m` ("WASH Relai": outbox, QR relay, deferred
upload, SMS fallback). All UI copy is French.

> Backend contract: Laravel API at `VITE_API_URL` (`/v1/wash/*`, `/v1/admin/*`,
> `/v1/mesh/*`, `/v1/notifications`). Mesh protocol spec lives in
> [mesh/README.md](../mesh/README.md).

---

## Stack (exact versions)

From [package.json](package.json) — every dependency, none omitted:

| Package | Version | Role |
|---|---|---|
| `react`, `react-dom` | `^19.3.1` | UI framework |
| `react-router-dom` | `^7.18.5` | Routing (`BrowserRouter`) |
| `tailwindcss`, `@tailwindcss/vite` | `^4.3.3` | CSS-first styling + Vite plugin |
| `@fontsource-variable/bricolage-grotesque` | `^5.0.0` | Display font (`font-display`) |
| `leaflet`, `react-leaflet` | `^1.9.4` / `^5.0.0` | Territory map |
| `recharts` | `^3.0.0` | Charts (trends, donuts, bars) |
| `qrcode` | `^1.5.4` | QR rendering (`QRCode.toDataURL`) |
| `html5-qrcode` | `^2.3.8` | QR camera scan + image-file scan |
| `libsodium-wrappers` | `^0.8.4` | E2E sealed-box + Ed25519 (PWA) |
| `vite` | `^8.3.5` | Dev server + build |
| `@vitejs/plugin-react` | `^6.1.2` | React Fast Refresh |
| `vite-plugin-pwa` | `^2.0.0` | Service worker + manifest (generateSW) |
| `typescript` | `~7.0.2` | Type checking (`tsc -b`) |
| `oxlint` | `^1.89.0` | Linter (`npm run lint`) |
| `@types/leaflet`, `@types/node`, `@types/qrcode`, `@types/react`, `@types/react-dom` | various | Type declarations |

---

## Scripts

| Script | Command | What it does |
|---|---|---|
| `npm run dev` | `vite` | Dev server with HMR |
| `npm run build` | `tsc -b && vite build` | Project-referenced typecheck (app + node configs), then production build + SW generation |
| `npm run lint` | `oxlint` | Fast lint, zero-config |
| `npm run preview` | `vite preview` | Serve the production `dist/` locally |

`tsc -b` builds both referenced projects ([tsconfig.json](tsconfig.json)):
[tsconfig.app.json](tsconfig.app.json) (app) and [tsconfig.node.json](tsconfig.node.json)
(Vite config). The build emits `dist/sw.js` (Workbox generateSW), `dist/manifest.webmanifest`,
`dist/registerSW.js`, hashed chunks — including lazy `MeshFieldPage-*` and
`PublicReportPage-*` chunks — plus the fonts, icons and CSS precached below.

---

## Routes (complete table)

Defined in [App.tsx](src/App.tsx). Guards: `RequireAuth` (any logged-in user),
`RequireAdmin` (`wash_admin` role, otherwise an inline "reserved" notice).

| Path | Page | Access | Usage |
|---|---|---|---|
| `/login` | `LoginPage` | public (redirects to `/` if logged in) | Email/password login, prefilled demo email |
| `/m` | `MeshFieldPage` (lazy) | **public, no login** | Field PWA: offline reports, QR, upload, SMS |
| `/signaler` | `PublicReportPage` (lazy) | **public, no login** | Citizen report form |
| `/` | `ConsolePage` | auth | AI console (chat + voice + library + demo) |
| `/admin/incidents` | `IncidentsPage` | auth | Interventions CRUD + status/assign/priority |
| `/admin/ecoles` | `SchoolsPage` | auth (create: admin) | Schools registry + create |
| `/admin/signalements` | `ReportsPage` | auth | Reports inbox + duplicate filter + create |
| `/admin/journal` | `JournalPage` | **admin only** | AI analyses journal (7 types) |
| `/admin/notifications` | `NotificationsPage` | auth | Notifications (unread filter, mark read) |
| `/admin/mesh` | `MeshPage` | auth | Mesh protocol demo (A→B→C simulator) |
| `/admin/reglages` | `SettingsPage` | **admin only** | LLM + STT provider profiles |
| `/admin` | — | — | Redirects to `/` |
| `*` | — | — | Catch-all redirects to `/` |

Providers wrap all routes: `ThemeProvider` → `AuthProvider` → `DialogueProvider`
(keyed by user email, resets per user). `/m` and `/signaler` are `React.lazy` with
French suspense fallbacks, so the console bundle stays lean. `main.tsx` rewrites a
`#/m` hash deep-link (desktop binary webview) to `/m` on boot.

---

## Pages (each page documented)

- **ConsolePage** (`src/pages/ConsolePage.tsx`, ~1014 lines) — the AI Mission Control.
  Chat with Sentinel (`api.converse`), progressive typewriter rendering
  (`CHUNK=8`, `TICK_MS=18`), waiting steps (`WaitingSteps`) + slow-wait actions after
  90 s, follow-up chips, agent cards (`AgentCardList`), voice dictation
  (`VoiceRecorder`) with transcript preview, TTS answers (`VoicePlayer` + cache),
  full-screen `VoiceMode`, dialogue library (projects/conversations, local-first then
  server sync), `WelcomeScreen` with animated bubbles, `DemoPlayer` (frozen 3-step jury
  script), and `DetailDrawer` drill-down into incidents/schools.
- **LoginPage** (`src/pages/LoginPage.tsx`) — email/password form, demo email prefilled
  (`admin@wash.cm`), error banner, live clock + status dot, ambient grid background.
  Logged-in users are redirected to `/`.
- **IncidentsPage** (`src/pages/IncidentsPage.tsx`) — interventions table with filters
  (status ×6, urgency ×4, category ×4, district, search), 3 sorts (AI score, recency,
  affected students), pagination, status transitions, assign-to-user (admin list),
  priority override (score + urgency), maintenance-log creation, `DetailDrawer` on row
  click. Uses `STATUS_FR`/`URGENCY_FR`/`CATEGORY_FR` labels.
- **SchoolsPage** (`src/pages/SchoolsPage.tsx`) — searchable/paginated school registry
  (district + text search), admin-only creation form with validation, detail drawer,
  formatted numbers (`fmtNum`).
- **ReportsPage** (`src/pages/ReportsPage.tsx`) — reports inbox: channel filter
  (voice/text/photo/call), duplicate filter (all/unique/dup), debounced remote school
  search (300 ms + stale-run guard), admin creation, `Pretty` JSON inspector,
  detail drawer.
- **JournalPage** (`src/pages/JournalPage.tsx`) — admin-only AI analyses journal.
  Seven real `analysis_type` values from the backend: `triage`, `repair`, `copilot`,
  `equity`, `epidemic`, `agent`, `agent_action` — each with label + tone badge,
  confidence meter, JSON payload view, pagination.
- **NotificationsPage** (`src/pages/NotificationsPage.tsx`) — notification feed with
  unread-only toggle, relative French timestamps ("il y a 2 h"), mark-one/mark-all
  read, critical-incident payload rendering (reference, urgency, AI summary),
  detail drawer jump to the incident.
- **SettingsPage** (`src/pages/SettingsPage.tsx`) — admin-only AI provider settings.
  Two profile kinds: LLM (`ModelProfile`: provider, base_url, model, vision/embed
  models, timeout, key) and STT (`SttProfile`: driver, model, tokens path, language,
  threads). CRUD + activate + live test (LLM sample / STT file-upload transcription)
  via the shared `ProfileForm`.
- **MeshPage** (`src/pages/MeshPage.tsx`) — authenticated mesh **simulator** (demo of
  the protocol, distinct from the real PWA): create an offline bundle on node A
  (Yokadouma), relay A→B→C with anti-loop guard, upload from node C to
  `POST /v1/mesh/bundles`, live mesh stats badge (`/v1/mesh/stats`). Links to `/m`.
- **MeshFieldPage** (`src/pages/MeshFieldPage.tsx`, ~785 lines) — the real field PWA,
  see the PWA section below.
- **PublicReportPage** (`src/pages/PublicReportPage.tsx`) — public citizen form (no
  account): school combobox with debounced search, category radio (4), urgency radio
  (4), optional affected-students count, description (10–4500 chars). Field errors in
  French, friendly submit errors (429/5xx/offline), success screen with incident
  `reference_code` + duplicate notice + "file another" reset. Posts
  `POST /v1/wash/reports` with a `[Signalement citoyen]` header composed into
  `message` (backend contract: only `school_id`/`channel`/`message`).
- **PlaceholderPage** (`src/pages/PlaceholderPage.tsx`) — tiny unused placeholder
  kept for scaffolding; not routed.

---

## `src/lib` (each module documented)

| Module | Role | Key exports |
|---|---|---|
| `api.ts` (~660 lines) | Typed API client: base URL, Bearer token in `localStorage`, 401 auto-logout, timeouts, guided FR error messages, `degraded:true` partial-response passthrough | `api` (40+ methods: auth, converse, transcribe, synthesize, schools, incidents, reports, notifications, journal, profiles…), `ApiError`, `ApiFailureKind`, `setToken/getToken`, `GUIDED_*_MESSAGE` |
| `mesh-sdk.ts` (453 lines) | **Vendored copy** of `mesh/sdk/mesh-sdk.ts` — do not edit here; CI diffs it (`tail -n +5` to skip the header). Zero-dependency DTN client | `MeshBundle`, `MeshOutbox` (localStorage, gc, add/update/remove), `createBundle`, `forwardBundle` (Spray-and-Wait), `serializeForQR`/`parseFromQR`, `splitMedia`/`chunkBytes`, `checksumOf`/`canonicalString`/`canonicalBytes`, `syncWithRelay`, `ackDelivered`, `uploadToLaravel` |
| `mesh.ts` | PWA↔protocol bridge: re-exports SDK + field helpers | `apiBase`, `smsGateway`, `isIOS`, `smsHref` (iOS `&body=` vs Android `?body=`), `smsText` (`WASH <CODE> <TYPE>` ≤160 chars), `cacheSchools`/`cachedSchools` (300 max), `outboxAdd` (+ Background Sync kick) |
| `mesh-sync.ts` | Best-effort background upload triggers | `MESH_SYNC_TAG` (`wash-mesh-upload`), `MESH_SYNC_MESSAGE`, `registerMeshSync()` (never throws: `registered/unupported/failed`), pure `shouldFlushOutbox({online, pendingCount, flushInFlight})` |
| `mesh-crypto.ts` | V2 E2E + signatures via libsodium (no homebrew crypto) | `fetchSealKey` (`GET /v1/mesh/key`), `sealMessage` (sealed-box, ORIGINAL base64 for PHP), `generateNodeKeypair`/`getOrCreateNodeSigningKey` (localStorage `wash_mesh_node_sign_sk`), `signBundle` (Ed25519 over canonical bytes, checksum recomputed), `verifyBundle` (fail-closed) |
| `mesh-outbox-status.ts` | Visible outbox states (SDK stores none: upload *removes* bundles) | `deriveOutboxView` (pure; hides media fragments), `bundleLabel`/`bundleDetail`, `outboxSummary` (FR screen-reader phrase), `loadOutboxMeta`/`saveOutboxMeta` (`wash_mesh_outbox_meta`, 20 sent max), statuses `pending/sending/failed` + recent sent |
| `install-prompt.ts` | In-app PWA install | `useInstallPrompt` (`canInstall/install/dismiss`, captures `beforeinstallprompt`), pure testable `isIOSDevice`, `isStandaloneDisplay`, `iosHelpDismissed`/`dismissIosHelp` (localStorage) |
| `streaming.ts` | Progressive waiting UX (SSE deliberately removed as a failure multiplier) | `UX_WAIT_TIMEOUT_MS` (90 s), `WAITING_STEPS` (Réception/Analyse/Outils/Réponse), `stepIndexForElapsed` (thresholds 0/3/12/40 s) |
| `dialogues.ts` | Dialogue library types + pure helpers | `DialogueMessage/ChatItem/ProjectItem`, `chatTitle` (42 chars), `fmtWhen` (fr-FR), `toMessagePayload` |
| `wash.ts` | FR labels, tones, formatters | `STATUS_FR/URGENCY_FR/CATEGORY_FR/CHANNEL_FR`, `urgencyTone/statusTone`, `fmtDate`/`fmtNum` (fr-FR), shared `INPUT_CLS` |
| `ttsCache.ts` | Bounded LRU TTS cache (20 entries, eviction revokes URLs; caller must never revoke). STT is never cached (stale audio → false triage) | `TTS_CACHE_CAPACITY`, `ttsCacheKey/getCachedTtsUrl/getSynthesizedUrl/clearTtsCache` |
| `demoScript.ts` | Frozen 3-step FR jury demo hitting the real backend (no mocks) | `DEMO_SCRIPT` (report leak → rank schools → Bonanjo trends), `DEMO_ASK_PAUSE_MS` (900), `DEMO_STEP_PAUSE_MS` (1800) |
| `richtext.tsx` | Safe mini-markdown for agent answers (no `innerHTML`): bullets, numbered lists, `**bold**`, line-split for progressive render | `renderRichText` |

Supporting app modules: `auth/AuthContext.tsx` (token+user persistence,
401 handler, logout beacon), `dialogues/DialogueContext.tsx` + `dialogues/context.ts`
(hook), `theme.tsx` (dark by default, `wash_admin_theme`), `nav.ts` (8 `NAV_ITEMS`,
2 admin-only), `main.tsx` (StrictMode + `#/m` hash rewrite).

---

## Components inventory

- **Primitives** — `ui.tsx`: `Button` (primary/secondary/ghost, sm/md), `Badge`
  (6 tones), `Card`, `PageHeader`, `Skeleton`, `EmptyState`, `ConfidenceMeter`,
  `Avatar`, `StatusDot`, `LiveClock`. `controls.tsx`: `Checkbox`, `Radio`, `Toggle`,
  `Select`. `crud.tsx`: `Field`, `Pager`, `ErrorBanner`, `Pretty` (JSON).
  `icons.tsx`: `Icon` + `IconName` set. `controls`/`ui` carry the `focus-visible`
  accent ring contract from `index.css`.
- **Shell** — `Layout.tsx` (sidebar nav from `NAV_ITEMS` + outlet), `EdgeDock.tsx`
  (edge dock + search trigger), `CommandPalette.tsx` (quick navigation),
  `WelcomeScreen.tsx` (console home: count, ask/speak/demo actions),
  `GuideEmpty.tsx` (guided empty states), `SlideDeck.tsx` (stat slides).
- **Agent & console** — `AgentCards.tsx` (~2578 lines: `AgentCardList`,
  `AgentCardView`, `FollowUps` — renders every card type from `converse`),
  `DetailDrawer.tsx` (incident/school slide-over, cross-links + ask follow-up),
  `StreamingStatus.tsx` (`WaitingSteps`, `SlowWaitActions`), `DemoPlayer.tsx`
  (replays `DEMO_SCRIPT` against the live backend).
- **Voice** — `VoiceControls.tsx` (`VoiceRecorder`, `VoicePlayer`,
  `ttsBase64ToObjectUrl`), `VoiceMode.tsx` (`VoiceMode` fullscreen + `VoiceModeToggle`),
  `VoicePreview.tsx` (transcript send/edit/discard), `ThresholdGauge.tsx` (mic level).
- **Data-viz** — `TrendChart.tsx` (`TrendChart`, `TrendDonut`, `TrendHBars`),
  `VizExtra.tsx` (`CalendarHeatmap`, `IncidentTimeline`, `BudgetCompare`),
  `TerritoryMap.tsx` (Leaflet map, offline detector: 4 s grace + 3 tile-error
  threshold, `TerritoryLegend`), `SentinelOrb.tsx` (4 states: idle/thinking/
  listening/speaking), `SentinelAvatar.tsx` (logo avatar).
- **Forms/settings** — `ProfileForm.tsx` (shared LLM/STT form, dynamic provider
  fields, `FormInitial`).

## The field PWA `/m` in detail

`MeshFieldPage.tsx` + `lib/mesh*.ts` + `install-prompt.ts`. Public, no login,
mobile-first (`max-w-2xl`), French throughout, node id shown in the header.

### Install prompt

- Chromium (Android/desktop) captures `beforeinstallprompt`, shows an in-app
  **Installer / Plus tard** card; `appinstalled` clears state.
- iPhone shows a dismissible help card (`wash_mesh_ios_help_dismissed`): the three
  Share → "Add to Home Screen" → Add gestures, plus the no-background-relay warning.

### Installing on iPhone (Safari)

1. Open the deployed `/m` URL in Safari (HTTPS in production, `localhost` exempt).
2. Tap **Share** (square with arrow up) → **Add to Home Screen** → **Add**.
3. Launch **WASH Relai** from the home screen: standalone display, `start_url: /m`.
4. First launch **with network**: the SW precaches the shell; the school list caches
   after the first successful load. Afterwards the form, outbox and QR relay work
   fully offline — only the upload needs connectivity.
5. iOS never uploads in the background — reopen the app (or tap Tout uploader) when
   back online.

### Installing on Android (Chrome)

1. Open `/m` in Chrome; the in-app **Installer** card appears (or menu → Install).
2. Accept the system prompt. The maskable 512 px icon adapts to the launcher shape.
3. Background Sync fires the deferred upload even if the tab was closed; the page
   fallbacks cover the rest.

### Precache: 21 entries

`workbox.globPatterns: **/*.{js,css,html,svg,png,woff2}`, `navigateFallback:
'/index.html'`, 4 MB per-file cap, `CacheFirst` for `https://fonts.*` (10 entries,
30 days). Verified in `dist/sw.js`: `precacheAndRoute` lists exactly **21 URLs** —
shell (`index.html`, main JS/CSS), both lazy chunks (`MeshFieldPage-*`,
`PublicReportPage-*`), Bricolage woff2 ×3, icons (192/512/maskable/apple-touch),
favicons, `manifest.webmanifest`, `registerSW.js`. Never cached: POSTs and API
responses (living data). Fonts runtime-cache is the only runtime route.

### Background Sync (best-effort) + fallbacks

Every `outboxAdd` (local create or QR ingest) calls `registerMeshSync()`, which
registers the `wash-mesh-upload` tag when `registration.sync` exists and never
throws otherwise. With generateSW no custom `sync` handler is wired, so the page
retries itself: `online` event, `visibilitychange`, SW `message` (future-compat
`MESH_SYNC_MESSAGE`), 30 s timer, plus an immediate kick on mount. All gates go
through pure `shouldFlushOutbox` (online + pending + no flush in flight).
Upload = `uploadToLaravel` → delivered bundles move to "recently sent" (max 20,
persisted), failures persist `{at, error}` per bundle id.

### Outbox states

`pending` (En attente, amber) → `sending` (Envoi…, all pending flip during flush)
→ removed on success (→ "Envoyés récemment", green) or `failed` (Échec +
Réessayer, first error hinted under the list). Media fragments stay internal
(counted, not listed); removing a manifest removes its fragments too. Live
`role="status"` summary (`outboxSummary`) doubles as the screen-reader announcement.

### QR show / scan / import-photo

- **Show**: per-manifest **QR** button renders `qrcode.toDataURL` (EC level M,
  512 px, margin 2) of `serializeForQR` (base64url JSON, ~0.5 KB text / ~900 chars
  signed V2). Too-big media bundles fail with a FR message.
- **Scan**: `Html5Qrcode` camera (`facingMode: environment`, 10 fps, 250 px box),
  stopped + cleared on unmount; HTTPS/permission failures explained in FR.
- **Import**: hidden file input → `scanFile` on a hidden div — same `ingestQrText`
  validation as the camera (incomplete bundle / already queued / unreadable QR).
- Ingest reuses `outboxAdd`, so received bundles also arm Background Sync.

### SMS fallback

Rendered only when `VITE_SMS_GATEWAY_NUMBER` is set. Type selector (P pump / L
latrine / E water-quality / H hygiene) + `sms:` deep link (`?body=` Android,
`&body=` iOS) with `WASH <CODE> <TYPE> [DETAIL]` truncated to one 160-char segment.
Requires a school code; otherwise a hint explains why it is inactive.

### E2E toggle, photo, voice

- **E2E** (`sealOn`, default ON): fetches `GET /v1/mesh/key`; when unavailable the
  checkbox disables with an explicit "en clair" warning. Text is sealed
  (message emptied); media uses encrypt-then-chunk (sha256 still covers cleartext).
- **Photo**: file picker → canvas downscale ≤1280 px → JPEG q0.7 → `MEDIA_MAX_BYTES`
  (2 MB) guard → `splitMedia` manifest + chunk fragments (32 KB each).
- **Voice**: `MediaRecorder` (opus/webm/mp4 probing) with 30 s auto-stop; same
  2 MB guard. Photo and voice are mutually exclusive; **Retirer** clears both.

### Vendored SDK + CI guard

`src/lib/mesh-sdk.ts` is a vendored copy of `mesh/sdk/mesh-sdk.ts` (header warns
against local edits). CI enforces identity:
`diff mesh/sdk/mesh-sdk.ts <(tail -n +5 frontend/src/lib/mesh-sdk.ts)`.
Field crypto (`mesh-crypto.ts`) signs with Ed25519 / seals with libsodium, same
primitives as the PHP relay and Python verifier.

## Environment variables

Build-time only (Vite `import.meta.env` — baked into the bundle, no runtime
override). Copy [.env.example](.env.example) to `.env` for local dev.

| Variable | Default | Effect |
|---|---|---|
| `VITE_API_URL` | `http://localhost/api` | API base URL for `api.ts`, school cache, seal key, mesh uploads/stats |
| `VITE_SMS_GATEWAY_NUMBER` | `""` (empty) | Village SMS gateway number; empty hides the SMS fallback card entirely |

Changing a value requires a rebuild. There are exactly two `VITE_*` variables.

## Design system

- **Tailwind v4, CSS-first** (`@import "tailwindcss"`, no JS config) via
  `@tailwindcss/vite`. Custom dark variant: `@custom-variant dark` on the `.dark`
  class, toggled by `ThemeProvider` (dark default, persisted as `wash_admin_theme`).
- **Semantic tokens** in `@theme` + `.dark` override: `primary`, `accent` (teal),
  `canvas`/`card`/`raised` (stone surfaces), `line`, `ink`/`ink-soft`/`ink-faint`,
  `danger` (+`danger-soft`), fonts `sans`/`mono`/`display` (Bricolage Grotesque),
  easings `snap`/`drawer`.
- **Custom CSS**: `.glass` liquid-glass panels (blur + saturate, disabled under
  `prefers-reduced-transparency`), `.scene-bg` immersive lagoon/abyss welcome scene
  with parallax vars (`--px/--py`), `.think-dot` breathing typing indicator,
  `.bg-grid` faint technical grid, themed thin scrollbars (accent on hover, code
  blocks keep native style), global `:focus-visible` accent ring, teal `::selection`.

## Accessibility & i18n

- French-only UI (`<html lang="fr">`, fr-FR dates/numbers, French aria labels).
  No i18n framework — copy is inline.
- Outbox `role="status"` live region, `role="alert"` on form submit errors,
  labelled QR/retry/remove buttons, combobox/listbox semantics on school pickers,
  radio groups for category/urgency, `aria-checked`/`aria-selected` states.
- Keyboard: visible focus ring everywhere; scanner/camera failures carry
  text alternatives (photo-QR import). `prefers-reduced-transparency` honored.

## Tests & checks

No unit-test runner is configured for the frontend; quality gates are:

```bash
npm run lint    # oxlint — must report 0 errors
npm run build   # tsc -b (app + node projects) then vite build + SW generation
```

CI (`../.github/workflows/ci.yml`, job `frontend`, Node 22): `npm install` →
vendored-SDK identity diff → `npm run build`. Manual checks worth repeating:
install `/m` on a real phone, kill the network, create a report, relay it by QR to
a second device, restore the network and confirm the upload; verify
`precacheAndRoute` in `dist/sw.js` still lists 21 entries including both lazy
chunks; toggle E2E off/on and confirm the cleartext warning states.

## Honest limits

- The PWA is not native: no Bluetooth sync (the Android app covers BLE), no push
  notifications (in-app feed only), no background upload on iOS — ever (Apple
  forbids it; the iOS help card says so).
- Background Sync is best-effort even on Android: with generateSW there is no
  custom `sync` handler — delivery ultimately depends on the page fallbacks.
- Server-side TOFU for node keys is not implemented: `node_pubkey` rotation raises
  no alert yet (noted in `mesh-crypto.ts`).
- All env vars are build-time: pointing a deployed bundle at another API means
  rebuilding.
- Camera/mic require HTTPS (or localhost) + user permission; offline map tiles are
  not cached (map degrades to a graceful offline legend).

## Folder structure

```text
frontend/
├── index.html            # FR meta, PWA metas, theme-color, root div
├── vite.config.ts        # react + tailwind + VitePWA (manifest, workbox)
├── package.json          # scripts + deps (see Stack)
├── tsconfig.json / tsconfig.app.json / tsconfig.node.json
├── .env.example          # VITE_API_URL, VITE_SMS_GATEWAY_NUMBER
├── public/               # favicon.svg, icons.svg, icons/*.png (PWA)
├── dist/                 # build output: sw.js, manifest, hashed chunks
└── src/
    ├── main.tsx          # StrictMode boot + #/m hash rewrite
    ├── App.tsx           # providers + complete route table
    ├── index.css         # Tailwind v4 theme, tokens, glass/scene CSS
    ├── theme.tsx         # dark-by-default ThemeProvider
    ├── nav.ts            # 8 NAV_ITEMS (2 admin-only)
    ├── auth/AuthContext.tsx
    ├── dialogues/        # DialogueContext + context hook
    ├── lib/              # api, mesh-sdk (vendored), mesh, mesh-sync,
    │                     # mesh-crypto, mesh-outbox-status, install-prompt,
    │                     # streaming, dialogues, wash, ttsCache, demoScript, richtext
    ├── components/       # 24 files: primitives, shell, agent, voice, viz, forms
    ├── pages/            # 12 files (11 routed + PlaceholderPage)
    └── assets/           # hero.png, vite.svg
```