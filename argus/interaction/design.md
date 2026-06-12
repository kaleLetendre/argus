# Compartment: interaction

> Status: draft. The user-interaction edge, in and out. Pure I/O; holds no domain
> logic. See [system_goal.txt](system_goal.txt) for the plain-language charter.

## Purpose

Handle the deliberate back-and-forth between a user and Argus. Take what a user
communicates (typing today; speech, and later more) and turn it into a clean message
for agents; take agents' replies and present them to the user (text, speech). It may
also render memory directly (a live view). interaction is all adapters and no domain
logic: if you deleted every other compartment, interaction would still just be
keyboards, microphones, speakers, and screens with nothing to say.

interaction is specifically the **user** channel. Passive perception of the world
(cameras watching, environmental data) would be a separate **sensors** system, and
physically acting on the world (motors, relays) a separate **actuators** system. Both
are added later through their own contracts, not folded in here. The split is by role,
not by device: a camera a user shows something to is interaction; a camera passively
watching is sensors.

## Owns (responsibilities)

- **Input adapters.** Keyboard today; later speech-to-text from a mic, and camera
  input used for interaction (e.g. a gesture). Each produces a clean message
  (text + metadata) and hands it to agents. Because interaction does the
  capture-to-text itself, agents never sees raw audio: a keyboard and a mic look
  identical to it.
- **Output adapters.** Terminal today; later text-to-speech and an on-screen UI. Each
  renders a `Reply` from agents, and may render memory directly (live view).
- **Wake / activation** (later): detecting the "argus" wake word belongs at this edge,
  before a message is sent.
- **Device lifecycle.** Opening/closing audio streams, UI windows, etc.

## Explicitly NOT responsible for

- Understanding the request (parsing/intent is agents').
- Any knowledge lookup or model call (it may *render* memory, not reason over it).
- Conversational focus (that's memory).
- Passively perceiving the world (that's a sensors system) or acting on it (that's an
  actuators system).

## Internal structure (current -> target)

| Now | Target |
|---|---|
| `cli.py`, `__main__.py` | `interaction/` first adapter (keyboard + terminal) |
| (new) | `interaction/` audio in (STT), audio out (TTS) |
| (new) | `interaction/` on-screen UI |

## Speaks (contracts)

- [interaction <-> agents](../contracts/interaction-agents.md) — sends user messages,
  renders replies.
- [memory <-> interaction](../contracts/memory-interaction.md) — live view +
  notifications.

## Invariants (must always hold)

- interaction holds no domain logic; it only captures and renders.
- It is the **user** channel only; passive sensing and physical action are separate
  systems, not added here.
- No silently-chosen STT/TTS engine (open decision); where speech-to-text runs is
  decided (inside interaction), which engine is not.
- An adapter failing (mic unplugged, TTS down) degrades to another adapter (e.g.
  screen) rather than taking the system down.

## Open questions

- STT and TTS engine choice (deliberately open).
- One session across simultaneous adapters (mic + screen) vs one per adapter.
