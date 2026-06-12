# Contract: interaction <-> agents

> Status: draft. The world <-> brain edge. The main request/response path: an
> utterance in, a reply out.

## Parties & direction

- **interaction -> agents:** recognized utterances (from keyboard/STT/vision).
- **agents -> interaction:** replies to render (speak/show), including unprompted pushes
  (e.g. study finished, a proactive nudge).

## Transport

- **Now:** in-process Python call (interaction's REPL calls agents, prints the result).
- **Later (no contract change):** agents run as a local service; interaction adapters
  (mic daemon, UI app) talk over a local socket/IPC. Only the adapter changes.

## Operations

### `interaction -> agents: submit(Utterance) -> Reply`
Hand agents a recognized utterance; get back a reply to render. Agents own the
whole turn behind this call (parse, query memory, compose).

### `agents -> interaction: render(Reply)`
Present a reply to a preceding utterance. In-process this is just `submit`'s return
value; it becomes a distinct call once output is streamed. Unprompted messages are
**not** renders: they go through `push(Prompt)` below (D40/D53).

### `agents -> interaction: push(Prompt)` (D40)
Originate an **unprompted** message to the user: a proactive question or an Event
follow-up that the study check-in loop produced ("did the cam caps hold at 18?"), or a
completed **user-requested research result** ("found it: 13 ft-lb per the FSM", D55c). This is
the outbound direction the reward loop needs; without it, proactive Questions and Event
follow-ups have nowhere to go. **Targeting:** deliver to a **live session** if one exists;
else **queue** it and surface at the user's **next interaction**; `urgent` items may push
to a default device as a notification. interaction owns the live-vs-queue decision. agents resolves every pushed ref to the **lineage head** before pushing and stamps
`supersedes_ref?` (the prior head) on the Prompt, so interaction, which is pure I/O and
walks no chains, replaces a queued undelivered Prompt by **simple id equality** against
`ref`/`supersedes_ref` (D59g; no double-asks across a reframe, D57h). Delivery is reported
back via `delivered(ref)` (D59f); agents stamps it through memory's `note_surfaced`
(D58j), so ask-spacing keys on actual surfacings (D57e).

### `interaction -> agents: delivered(ref)` (D59f)
Report that a pushed Prompt was **actually surfaced** to the user (immediately for a live
push; at delivery time for a queued one, when the originating fire-and-forget Task no
longer exists to hear it). Handled by agents **plumbing**, mechanically, no model call:
agents invokes memory's `note_surfaced(ref)` so ask-spacing sees the surfacing (D57e/D58j).
Only **Question/Event refs** are stamped; a `kind:"result"` Prompt's Task ref is not (a
delivered result needs no ask-spacing, D60).

## Data shapes

```
Utterance {
  text:          string        # recognized words
  source:        "keyboard" | "voice" | "vision" | ...
  session_id:    string        # opaque to interaction; "same conversation"
  timestamp:     string        # ISO-8601, stamped by interaction
  confidence?:   float         # STT confidence, when applicable
  reply_to_ref?: id            # set when this answers a pushed Prompt (D45): routes the
                               # answer back to the originating Question/Event
}

Reply {
  text:        string
  kind:        "answer" | "navigation" | "status" | "disambiguation" | "error"
  found:       bool
  display?:    object        # optional rich/UI hints; interaction may ignore
  speakable?:  bool          # whether TTS should voice it (default true)
}

Prompt {                     # an unprompted outbound message (D40)
  text:           string     # the question / follow-up / result to surface
  kind:           "question" | "follow-up" | "result"   # result = user-requested research (D55c)
  ref:            id         # the Question/Event/Task it came from, already resolved to the
                             # lineage head by agents (D59g; for an answer to route back)
  supersedes_ref?: id        # the prior lineage head, so interaction can replace a queued
                             # Prompt by simple id equality (D59g)
  urgent?:        bool       # push to a default device vs queue for next interaction
}
```

## Guarantees

- agents always return a `Reply`; never throw across this edge for a normal "I
  don't know" (that's `found: false`).
- interaction never interprets `text`; it only renders. No domain logic leaks down.
- **Proactive round-trip (D45):** when interaction surfaces a `push(Prompt {ref})`, it
  remembers the `ref` and stamps the user's answering `Utterance` with `reply_to_ref = ref`,
  so the answer routes back to the Question/Event with no NL re-inference. A *queued*
  follow-up re-binds the same way when it is finally delivered.

## Errors

- Internal failure -> `Reply { kind: "error", found: false }` with a human-safe
  message; interaction renders it.
- interaction adapter failure (mic/TTS down) is interaction's to handle (degrade to another
  adapter); not reported back here.

## Versioning / open questions

- Streaming: partial transcripts in, chunked speech out. Note D30's mid-turn narration
  ("let me look that up", "two sources disagree, checking") needs this (or a multi-Reply
  turn); it must land before research-during-a-live-turn does.
- Wake-word handling stays in interaction (below this contract).
