# 🚰 WASH Sentinel

### The dashboardless AI guardian for school water & sanitation emergencies.

[![Stack](https://img.shields.io/badge/stack-Laravel%2012%20%7C%20FastAPI%20%7C%20React-blue)]()
[![AI](https://img.shields.io/badge/AI-Meta%20Llama%20%7C%20Omnilingual%20ASR%20%7C%20WhatsApp-0668E1)]()
[![Fresh code](https://img.shields.io/badge/code-100%25%20fresh%20commits-green)]()
[![Status](https://img.shields.io/badge/status-working%20MVP-success)]()

> 🎬 **Demo video:** _coming soon_ (`docs/demo.mp4`) · **Live jury URL:** _on request_

> **One omnipresent AI agent instead of dashboards.** School directors report a broken pump by text, voice note, photo or WhatsApp — in French or a local language like Douala. Sentinel triages, deduplicates, prioritizes, dispatches fairly across the territory, and advises: *repair or replace?*

Built with 💧 for the **Meta Hackathon** — powered by **Meta Llama**, **Meta Omnilingual ASR** and the **WhatsApp Cloud API**. Starting pilot: **Cameroon 🇨🇲**.

---

## 1. The problem

- **429M children** lack basic drinking water at school, **460M** lack basic sanitation and **545M** lack basic hygiene ([WHO/UNICEF JMP 2015–2025](https://data.unicef.org/resources/jmp-wash-in-schools-2026/)). In rural Cameroon, a broken handpump can leave **400+ pupils without drinking water for weeks**.
- Reports arrive chaotically — phone calls, WhatsApp voice notes in local languages, paper notes — and **die in inboxes**. Five teachers reporting the same leak create five tickets… or zero action.
- Maintenance is unfair by default: the loudest, closest, best-connected school gets served first. Remote schools and **adolescent girls** (first to drop out when latrines fail) are forgotten.
- Communes burn budgets on endless patch-repairs instead of strategic replacement.

## 2. The solution

WASH Sentinel turns every chaotic field report into **one triaged, deduplicated, prioritized incident** — then acts as the territory manager's incorruptible copilot:

| Signal in (multimodal) | Sentinel pipeline | Action out |
|---|---|---|
| 📝 Text, 🎙️ voice note, 📸 photo, 💬 WhatsApp, in FR / Douala / … | STT → structured extraction → duplicate check → priority score | Ticket + reference code + voice confirmation |
| "Which schools should we replace instead of repair?" | Capex/Opex decision copilot over maintenance history | Replace-vs-repair verdict + savings plan |
| "Who do we serve first this week?" | Territorial equity index + route optimizer | Fair ranking + grouped tours + official justification note |
| 3 schools, same district, yellow water | Epidemic cluster detector | ⚠️ Contamination / cholera-risk alert |

**No dashboard to learn.** An omnipresent agent answers in natural language and generates **cards, lists and charts on demand** (incident cards, repair-trend charts, dispatch plans).

## 3. Why it wins 🏆

1. **Dashboardless by design** — a real agent loop with native function-calling and 6 tools (`analyze_school`, `rank_schools_by_need`, `summarize_district`, `explain_incident`, `repair_trends`, `prepare_report`), not a chatbot wrapper.
2. **Meta-native, end to end** — Llama for reasoning, Omnilingual ASR for 1,600 languages (Douala included), WhatsApp for the last mile.
3. **Equity is the algorithm** — a transparent fairness score (days without water × health risk × girls' impact × isolation bonus) kills favoritism and produces an auditable public justification.
4. **Repair-vs-repair economics** — the copilot computes cumulative repair cost vs. new-equipment cost (MTBF, school-days lost) and says *stop patching, replace with solar pumping*.
5. **Model independence** — switch local ↔ cloud LLM/STT **at runtime from the admin Settings page**. No redeploy, no code change. API keys encrypted at rest.
6. **Runs where it's needed** — full local stack on a CPU-only i5 (Llama 3.2 3B, ONNX int8 ASR). Cloud profiles available for zero-GPU demo day.

## 4. 🎬 3-minute jury demo script

_Golden path with example outputs — run it live after `./start.sh`._

1. **Report** — *« Ici école Saint-Paul, la pompe d'eau potable est brisée depuis ce matin, 400 élèves sans eau… »* (text or voice note) → incident created, **CRITICAL**, priority 95/100, reference `WASH-2026-0042`, voice confirmation generated.
2. **Duplicate** — send *« Problème d'eau à Saint-Paul »* → `is_duplicate: true`, attached to the parent, severity bumped. No ticket spam.
3. **Photo** — upload a burst pipe photo → vision check (WASH-related ✓), visual severity score fused into priority.
4. **Copilot** — *« Which schools in Douala got the most interventions this year — repair or replace? »* → ranked answer + savings plan + trend chart card.
5. **Equity** — *« Plan this week's tours »* → forgotten rural school ranked #1 over the downtown drip, grouped route saving 100+ km of fuel, official transparency note generated.
6. **WhatsApp** — same report via the WhatsApp simulator → identical pipeline, confirmation reply.

## 5. Architecture

```text
  Directors / Citizens                    Territory managers / Admins
  (text · voice · photo · WhatsApp)       (agent chat · generated cards/charts)
            │                                            ▲
            ▼                                            │
┌───────────────────────┐    REST + X-LLM/X-STT headers  │   ┌────────────────────────┐
│  Laravel 12 API       │◄──────────────────────────────►│───│  FastAPI AI Engine     │
│  Schools · Incidents  │                                │   │  Llama · Embeddings    │
│  Reports · RBAC       │─────────────┐                  │   │  Whisper · Omnilingual │
└───────────────────────┘             │                  │   │  Vision · Agent loop   │
            │                         ▼                  │   └────────────────────────┘
            │               ┌──────────────────┐         │              │
            └──────────────►│   PostgreSQL 16  │◄────────┘              ▼
                            │  + ai_analyses   │              ┌──────────────────┐
                            │  (audit trail)   │              │ Ollama (local)   │
                            └──────────────────┘              │ or any /v1 cloud │
                                                              └──────────────────┘
```

**Services** (`compose.yaml`): `laravel` (API), `queue` (WhatsApp + notifications worker), `pgsql`, `ai-engine`, `ollama`, `frontend` (React admin).

**Repo map:**

```text
WASH-SENTINEL/
├── compose.yaml, start.sh, stop.sh, .env.example
├── backend/                 # Laravel 12 API (SOLID: Contracts + Services)
│   ├── ai-engine/           # FastAPI: providers, agents, tools, STT
│   ├── app/Models|Services|Jobs|Notifications
│   └── database/migrations|seeders
├── frontend/                # React admin (login + AI Settings; public agent widget next)
└── models/                  # local voice models (git-ignored)
```

## 6. Quickstart

**Prerequisites:** Docker + Docker Compose (Docker Desktop on Windows/WSL works).

```bash
./start.sh
```

The script creates missing `.env` files, builds and starts all containers, runs migrations + seeders (Cameroon schools, roles, AI profiles) and pulls Ollama models. Then open:

| Service      | URL                        |
|--------------|----------------------------|
| Admin console| http://localhost:5173      |
| Laravel API  | http://localhost/api       |
| AI engine    | http://localhost:8000/docs |

**Demo accounts** (password: `password`): `admin@wash.cm` · `tech@wash.cm` · `directeur@ecole.cm`

```bash
./stop.sh            # stop, keep data
./stop.sh --volumes  # stop + wipe database and Ollama models
```

> If `APP_PORT` changes in `.env`, mirror it in `VITE_API_URL` (e.g. `http://localhost:8080/api`).

## 7. No local models? Use a cloud API in 60 seconds ☁️

Ollama pulls can fail on restricted networks — the stack stays fully usable via an external OpenAI-compatible endpoint (Groq, Together, OpenAI, Meta Llama API…):

1. Open the admin console → **AI Settings** → **New LLM profile**.
2. Provider: `API externe (format OpenAI)`, e.g. Groq: base URL `https://api.groq.com/openai/v1`, model `llama-3.3-70b-versatile`, paste your API key.
3. **Test**, then **Activate** — every agent call switches instantly, no restart.

Same flow for speech: `API cloud (OpenAI / Groq)` STT profile with `whisper-1`. Local Ollama can be (re)pulled anytime with `docker compose exec ollama ollama pull llama3.2:3b`.

## 8. API overview

**Laravel** (`/api/v1`): `POST /auth/token` · `GET /wash/schools|reports|incidents` · `POST /wash/reports` · `POST /wash/agent/chat|converse|dispatch-plan|epidemic-scan` · `GET|POST /admin/model-profiles|stt-profiles` (+ `/activate`, `/test`) · `POST /whatsapp/webhook` (+ `GET` verify).

**AI engine** (`:8000`): `/health` · `/v1/wash/extract|check-duplicates|triage|analyze-image|generate-repair-plan|detect-epidemic-risk` · `/v1/wash/copilot/chat|replace-vs-repair` · `/v1/wash/equity/dispatch-plan` · `/v1/agent/chat` · `/v1/voice/transcribe|synthesize` · `/v1/admin/provider-types|test-provider|stt-types|test-stt`.

Full interactive reference: http://localhost:8000/docs

## 9. Voice & local languages 🗣️

- **Whisper.cpp** (local, CPU) for French voice notes.
- **Meta Omnilingual ASR** via `sherpa-onnx` (ONNX int8, CPU-friendly): 1,600 languages including **Douala (`dua_Latn`)**, Bassa, Ewondo. Each school sets its `default_language`.
- **Piper TTS** speaks confirmations back ("Your report WASH-2026-0042 is registered, priority HIGH…").

To enable Omnilingual, drop the [~700 MB model + tokens](https://huggingface.co/csukuangfj/sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-int8-2025-11-12) into `models/omnilingual/` and activate the profile in AI Settings.

## 10. WhatsApp channel 💬

`MetaWhatsAppService` (Cloud API) + `ProcessWhatsAppMessage` job + `school_contacts` routing: directors report from WhatsApp, Sentinel replies with the reference code and status. A **simulator mode** replays the full flow for jury demos without Meta credentials; set `WHATSAPP_*` in `backend/.env` + webhook to go live.

## 11. Engineering you can audit 🔒

- **SOLID**: PHP contracts (`AiEngineClient`, `IncidentTriage`, `WhatsAppClient`) with container bindings; Python abstractions (`BaseLLMProvider`, `BaseSTTProvider`) + registries — agents depend on interfaces, never on Ollama.
- **Security**: Sanctum tokens, Spatie RBAC (reporter / technician / admin), API keys encrypted in DB (masked in UI), strict request validation, rate limiting on auth/report/webhook endpoints, every AI decision journaled in `ai_analyses`.
- **Resilience**: deterministic triage fallbacks keep reporting alive if the AI engine is down.
- **Tests**: PHPUnit suite (triage, duplicates, RBAC, WhatsApp, agent loop, notifications) green; Python probes cover LLM/STT/agent wiring.
- **Traceability**: 100% fresh code, committed step by step — no copy-paste from previous projects.

## 12. Roadmap

- [ ] Public agent widget (chat + cards/charts, express report, tracking by reference, FR/Douala toggle)
- [ ] Admin pilot console (incidents, schools, notifications UI)
- [ ] Live WhatsApp credentials + Meta app review
- [ ] True Douala field-audio validation of Omnilingual
- [ ] Final end-to-end demo rehearsal 🎤

---

*WASH Sentinel — built fresh for the Meta Hackathon. Leave no school behind.* 💧🇨🇲
