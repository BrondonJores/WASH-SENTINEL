# WASH Sentinel — Jury Demo Happy Path (10 minutes)

> One story, four acts: a school director reports a breakdown in her own
> language, Sentinel triages it, the operator decides with real numbers,
> and the field gets notified. Nothing here is a mock — every step runs
> on the live stack (Laravel 12 + FastAPI AI engine + WhatsApp Cloud API).

## Before the jury enters (5 min setup)

1. `./start.sh` — all containers green (`laravel`, `ai-engine`, `ollama`,
   `pgsql`, `queue`, `frontend`).
2. Warm the local LLM once (cold CPU is slow on the first call):
   `docker compose exec ollama ollama run llama3.2:3b "Reply OK"`.
3. Have ready: the presenter's phone with WhatsApp (verified school
   contact), the golden voice note (10 s, Ghomala', Western Cameroon),
   one breakdown photo (tap/pipe), projector on the Sentinel console.
4. Recommended: local models for the show (sovereignty story), Meta
   cloud already configured in Settings as the silent fallback.

## Act 1 — The field reports (2 min)

**Say:** "Everything starts in the field, not on a dashboard. A school
director in Cameroon reports a breakdown the way she actually
communicates: a WhatsApp voice note, in her own language."

1. Play the Ghomala' voice note to the WhatsApp number.
2. Show the reply on the phone: transcription, incident ref
   (`WASH-2026-XXXX`), priority, *"we will write to you here as soon
   as it moves forward."*
3. Send a second report of the same breakdown as plain text.
   **Say:** "Five teachers report the same broken pump. Watch:"
   reply is *"Already received"* — merged, no duplicate ticket.

## Act 2 — The agent, not a dashboard (3 min)

**Say:** "There is no dashboard to learn. Operators talk to Sentinel,
and it generates cards, charts, maps and decks on demand."

1. Type: *"Give me today's reports."*
   → incident list card, scoped to the day (not the repair journal).
2. Type: *"Prepare a report."*
   → report scoped to the school just discussed (not the whole
   territory) — this is conversational scope, not keyword search.
3. Type: *"Trends for Bonanjo over 3 months."*
   → trend chart card (costs, breakdowns, days without service).
4. Type: *"Show me the territory map."* → interactive map card.

## Act 3 — The decisions (3 min)

**Say:** "Reporting is easy. Deciding fairly with public money is the
hard part. Three engines do that:"

1. Type: *"Ngok school — repair or replace the equipment?"*
   → Capex/Opex matrix: repair ratio, breakdown frequency, 24-month
   savings, replacement recommendation.
2. Type: *"Which schools need help most?"*
   → equity ranking (days without water × health risk × isolation ×
   girls' schooling impact), grouped tour on the same road axis, and
   the transparency note: *"why school X goes before school Y"* —
   the shield against favoritism.
3. Type: *"Build the decision file for Mvila."*
   → decision-maker dossier: factual figures only, printable, with a
   generated poster. **Say:** "No invented numbers — every figure is
   traced to the database."

## Act 4 — The loop closes (1 min 30)

**Say:** "And the promise from Act 1 is kept — automatically."

1. In the incident page, move the incident to *In progress*, then log
   an intervention (cost + notes).
2. The director's phone buzzes twice, live: status update, then the
   logged intervention with cost.
3. Mention: *"STOP"* unsubscribes; a new report re-subscribes.
4. Flash the admin CRUD pages (schools, incidents, teams, costs).
   **Say:** "We never trust the AI 100% — every figure here is
   human-verifiable."

## Closing line (30 s)

> "WASH Sentinel is not a chatbot. It has ears for local languages,
> eyes for breakdown photos, memory against duplicates, a fairness
> engine for public money — and it closes the loop with the field,
> in the language of the field."

## If something fails live

| Failure | Fallback (no panic, no silence) |
|---|---|
| Voice transcription slow | "The local model runs on CPU — sovereignty has a cost." Show the already-triaged text report meanwhile. |
| LLM answer slow (>60 s) | Switch model to Meta cloud in Settings (30 s), re-ask. |
| WhatsApp message delayed | Queue worker lag — show the incident already created in the console, the message lands seconds later. |
| No network for cloud | Everything runs local (Ollama + Whisper + Omnilingual) — say it, it's the sovereignty argument. |
| Wrong tool answer | Rephrase simply ("Summarize district Mvila") — the guided fallbacks always propose the next step. |

## One-line feature map (if the jury asks "what else?")

Voice/text/photo/WhatsApp intake · FR/EN + Douala/Ghomala' · duplicate
detection · repair-vs-replace copilot · territorial equity dispatcher ·
trends/heatmap/map/deck/dossier generation · WhatsApp progress
notifications with STOP · human verification pages · local-first,
cloud-capable, model-independent (switch from Settings).
