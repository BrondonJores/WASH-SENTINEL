# WASH Sentinel — CapCut Pro AI Pack (jury cut 3:00)

Paste-ready inputs for CapCut Desktop Pro: Script-to-Video ("Match your media"),
auto captions EN, overlays, export checklist. Voice-over is English; on-screen
French (field language) is part of the story, not a bug.

## 0. Assets to upload (in this order)

| # | File | Content |
|---|---|---|
| 1 | `clip1.mp4` | Login + Sentinel orb reveal |
| 2 | `clip2.mp4` | WhatsApp EN report + leak photo |
| 3 | `clip3.mp4` | Duplicate -> "Already received" |
| 4 | `clip4.mp4` | Console: reports / Bonanjo / trends / map |
| 5 | `clip5.mp4` | Repair-vs-replace matrix |
| 6 | `clip6.mp4` | Equity ranking |
| 7 | `clip7.mp4` | Decision dossier + poster |
| 8 | `clip8.mp4` | Status + logged repair + 2 phone buzzes |
| 9 | `intro.mp4` / `outro.mp4` | Face cam (or AI B-roll, see §3) |
| 10 | `voiceover.mp3` | Your recorded EN VO (or use CapCut TTS, §4) |

## 1. Scene-by-scene script (paste into Script-to-Video)

Ratio 16:9. Tone: professional / storytelling. Media: Match your media.

**Scene 1 — INTRO (0:00-0:10, intro.mp4)**
VO: "In Cameroon, when a school's water fails, reporting it is chaos —
calls, paper, silence. WASH Sentinel changes that. Watch."
Overlay: `100% open source — Laravel 12 · FastAPI · Ollama · Docker`

**Scene 2 — NO DASHBOARD (0:10-0:20, clip1.mp4)**
VO: "No dashboard to learn. Operators talk to Sentinel — and it answers
with cards, charts, and maps."
Edit: timelapse on login typing, slow-mo on orb reveal.

**Scene 3 — THE FIELD REPORTS (0:20-0:50, clip2.mp4)**
VO: "Everything starts in the field. A school director reports a breakdown
the way she really communicates — a WhatsApp message in English, with a
photo of the leak. Sentinel triages it and replies with a case reference —
in seconds."
Edit: split-screen phone + console; zoom on `WASH-2026-XXXX`; CUT all
waiting time (jump cut straight to the reply).
Overlay: `Local-first AI — Meta Llama · Whisper`

**Scene 4 — NO DUPLICATES (0:50-1:02, clip3.mp4)**
VO: "Five teachers report the same pump. Watch — merged. No duplicate
ticket, ever."
Edit: jump cut straight to "Already received".

**Scene 5 — THE AGENT (1:02-1:32, clip4.mp4)**
VO: "Back at headquarters, one question is enough. Today's reports.
Bonanjo's file. Three-month trends. The territory map. Every visual is
generated on demand — scoped to the day, to the school, never mixed."
Edit: 1 cut = 1 card (4 fast cuts); keep only card reveals.
Overlay: `Model-independent — local ↔ cloud in Settings`

**Scene 6 — REPAIR OR REPLACE (1:32-1:52, clip5.mp4)**
VO: "Reporting is easy. Spending public money wisely is hard. Sentinel
scores repair versus replace — ratio, frequency, two-year savings."
Edit: zoom on ratio %, frequency, savings; 1 s hold on verdict.

**Scene 7 — FAIRNESS (1:52-2:07, clip6.mp4)**
VO: "Need is scored, not shouted. The quiet rural school outranks the
loud downtown one."
Edit: highlight the point gap between rank 1 and 2.

**Scene 8 — THE DOSSIER (2:07-2:27, clip7.mp4)**
VO: "And when it's time to decide: a decision-maker dossier — real figures
only, printable, with a poster. No invented numbers."
Edit: fast scroll of dossier, 2 s fullscreen on poster.
Overlay: `Sovereign by design — runs fully offline`

**Scene 9 — THE LOOP CLOSES (2:27-2:52, clip8.mp4)**
VO: "The promise is kept — automatically. Status change, logged repair with
its cost — the director is notified on WhatsApp. And every figure stays
human-verifiable."
Edit: split-screen: status click -> phone buzz 1; log 25,000 -> buzz 2;
quick flash Schools / Journal / Settings.

**Scene 10 — OUTRO (2:52-3:00, outro.mp4)**
VO: "WASH Sentinel: ears for local languages, eyes for breakdowns, memory
against duplicates, fairness for public money."
Edit: end card with open-source stack + `WASH Sentinel — Meta Hackathon 2026`.

## 2. CapCut click-path (Desktop Pro)

1. AI Video Maker / Script-to-Video -> paste §1 -> **Match your media**
   (Local materials) -> upload clips in order -> 16:9 -> Generate.
2. Refine on timeline: cut every AI/server waiting second (the AI won't
   know these are dead time — 8 manual cuts max).
3. Captions -> Auto captions -> language **English** -> sober animated
   style (no karaoke). Fix `WASH-2026-XXXX` and `XAF` spellings by hand.
4. Add the 4 overlays (§1) as text layers, bottom-third, 3 s each.
5. Background music low (-20 dB), normalize VO, sober transitions only.
6. Export 1080p 16:9 (jury projection). Total must read ≤ 3:00.

## 3. B-roll prompts (if no face cam, for CapCut AI media)

- Intro: "African school courtyard with hand water pump, morning light,
  children in background, cinematic wide shot, photorealistic".
- Outro: "Smiling African schoolchildren drinking clean water from a tap,
  slow motion, warm light, photorealistic".

## 4. Full VO transcript (for TTS fallback or caption check)

"In Cameroon, when a school's water fails, reporting it is chaos — calls,
paper, silence. WASH Sentinel changes that. Watch. No dashboard to learn.
Operators talk to Sentinel — and it answers with cards, charts, and maps.
Everything starts in the field. A school director reports a breakdown the
way she really communicates — a WhatsApp message in English, with a photo
of the leak. Sentinel triages it and replies with a case reference — in
seconds. Five teachers report the same pump. Watch — merged. No duplicate
ticket, ever. Back at headquarters, one question is enough. Today's reports.
Bonanjo's file. Three-month trends. The territory map. Every visual is
generated on demand — scoped to the day, to the school, never mixed.
Reporting is easy. Spending public money wisely is hard. Sentinel scores
repair versus replace — ratio, frequency, two-year savings. Need is scored,
not shouted. The quiet rural school outranks the loud downtown one. And when
it's time to decide: a decision-maker dossier — real figures only,
printable, with a poster. No invented numbers. The promise is kept —
automatically. Status change, logged repair with its cost — the director is
notified on WhatsApp. And every figure stays human-verifiable. WASH
Sentinel: ears for local languages, eyes for breakdowns, memory against
duplicates, fairness for public money."
