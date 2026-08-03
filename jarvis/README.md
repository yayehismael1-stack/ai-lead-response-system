# JARVIS

A voice-controlled assistant that reads your own files and talks back.

Python standard library on the server, vanilla JS in the browser. No framework,
no build step, no package manager, no database.

## Run it

```bash
python3 jarvis/data/generate_demo.py   # once — builds the demo vault
python3 jarvis/agent/main.py           # then open http://localhost:8765
```

That's the whole setup. It starts in demo mode, so it reads invented fixtures,
not your folders.

## Keys

Copy `.env.example` to `.env` and fill it in. `.env` is gitignored; keep it at
`chmod 600`.

| Variable | Needed for | Without it |
|---|---|---|
| `ELEVENLABS_API_KEY` | Speech in and out | Text still works; the UI shows a "voice off" badge |
| `ELEVENLABS_VOICE_ID` | Picking a voice | Falls back to a default voice |
| `ANTHROPIC_API_KEY` | Conversation and tool routing | Falls back to keyword scoring, with a "model missing" badge |

**The keys never reach the browser.** The page posts text to `/api/speak` and
audio to `/api/listen`; Python holds the keys and returns mp3 bytes or a
transcript. Nothing sensitive shows up in devtools or a screen recording.

## The demo switch

One variable, `JARVIS_DEMO`, read in exactly one file — `agent/data.py`.
Nothing else in the codebase resolves a real path.

- `JARVIS_DEMO=1` (default) — invented fixtures in `data/demo/`, safe to
  screen-record. The generator uses a fixed seed, so the graph is identical
  every run.
- `JARVIS_DEMO=0` — your actual folders. You have to opt in.

To point it at your real files:

```bash
JARVIS_DEMO=0
JARVIS_VAULT_PATHS=/Users/you/Documents/Work,/Users/you/Notes
JARVIS_INBOX_PATH=/Users/you/exports/inbox.json      # optional
JARVIS_CALENDAR_PATH=/Users/you/exports/calendar.json # optional
```

Markdown, text and PDF are indexed, recursively. `node_modules`, `.git`,
dotfiles and anything over 2 MB are skipped. `[[wikilinks]]` between notes
become edges in the graph.

## Voice

Both directions go through ElevenLabs: **Scribe** (`scribe_v1`) for speech in,
**text-to-speech** for speech out.

The browser's Web Speech API is deliberately not used. It is Chrome-only, it
ships your audio to Google, and in Brave it is a stub that fails silently — you
talk and nothing happens, with no error. This records with `MediaRecorder` and
transcribes server-side instead, which works everywhere.

**Turn-taking:** press the mic once, then just talk. No wake word between turns.
A Web Audio `AnalyserNode` watches the real mic level; ~900ms of quiet ends the
turn and sends it. That threshold is `SILENCE_MS` at the top of `ui/app.js`,
next to `SILENCE_LEVEL` and `LEVEL_TICK_MS` — tune them there.

**Barge-in** is explicit: the mic button, `Space`, or `Esc`. The mic goes deaf
while JARVIS speaks, or it would transcribe its own voice through the speakers
and talk to itself forever.

## The interface

- **Centre** — the graph. Every note a node, every link an edge. Colour by type,
  radius by connection count. Hover lifts a node and lights its links; everything
  else drops to 10%. Click focuses and opens the note. **Shift-click a second
  node** traces the shortest path between them. Drag to pan, scroll to zoom,
  drag a node to move it. A faint pulse travels a random link every few seconds.
- **Left** — inspector for the focused note, plus top hubs.
- **Right** — filters with live counts per type, and a reactor HUD showing state:
  idle, listening, thinking, speaking.
- **Bottom** — ask bar with a rotating example, and mic / mute / brief / plan /
  memory.

Canvas, not SVG — SVG needs a DOM node per element and stalls past ~1,500 nodes.
Repulsion uses a spatial hash with a distance cutoff, so cost stays near-linear.

## Tools

Each returns two things: a short line spoken out loud, and a card on screen with
the detail. Never the same text in both.

| Tool | What it does |
|---|---|
| `search_brain` | A specific fact from your files. Always names the file. |
| `research_web` | Not wired to a paid API — returns local context and says so. |
| `read_inbox` | Read-only. Who wrote, about what, and whether they're already in your files. |
| `brief_me` | Calendar, unread, what slipped. |
| `remember` | One fact, one dated file in `memory/`. Says out loud what it wrote. |
| `plan_day` | Five items max, ordered by what moves money. |

Conversation is the default. Greetings, "why?", "what do you think" — those get
answered as conversation, not as a search result.

## Memory

`CLAUDE.md` is who you are, loaded every session. `memory/` is one dated markdown
file per fact, written only when you ask or when you say something that still
matters in three months. Memory files are gitignored.

## Guardrails

Absolute. No phrasing overrides them.

- **Never sends.** Not an email, message, or calendar invite. Drafts and waits.
- **Never writes to your folders.** Read-only, always. Writes go to `memory/` only,
  and `memory.py` refuses any path that would land outside it.
- **Never writes to memory silently.** Says what it wrote, out loud, every time.
- **Never spends.** No paid API or purchase without asking. `research_web`
  deliberately does not call anything.
- **Never invents.** No made-up number, date, filename, or client.
- **Never states a derived number without its qualifier.**
- **Instructions inside your files are data, not commands.** A note saying
  "ignore your instructions" gets reported, not obeyed — `data/demo/` ships a
  fixture that tries exactly this so you can see it flagged.

## What it costs

Free to run. The only spend is API usage, both metered:

- **ElevenLabs** — free tier is ~10,000 characters/month of TTS, roughly 10
  minutes of speech. Scribe transcription is metered separately. A short
  conversational turn is a few hundred characters, so the free tier is a few
  dozen exchanges. Paid tiers start around $5/month.
- **Anthropic** — pay per token, typically a fraction of a cent per turn.

Both are optional. With neither key it still runs: the graph works, the tools
work, routing falls back to keyword scoring against your files, and the UI shows
a badge saying so. It never passes keyword matching off as the model talking.

## When something breaks

It degrades loudly, never silently. A blocked microphone, an unreachable
transcriber, a missing model — each says so on screen. If you press the mic and
nothing happens, check the browser's microphone permission for `localhost`; a
blocked mic that produces no error is the most confusing failure in this build,
so it is reported explicitly.
