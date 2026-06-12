# Compartment: agents

> Status: draft. The turn orchestrator and all "thinking power". In the mesh it
> talks directly to both interaction and memory (D15).

## Purpose

Drive a turn end to end and broker all model calls. Agents take an utterance from
interaction, understand it, get what's needed from memory, and compose the reply - "decide
what to call and return the response". It is also the single owner of every model
call, so model access has exactly one chokepoint (one place to configure the
connection and audit cost).

## Owns (responsibilities)

- **Turn orchestration.** utterance -> route intent -> tool loop (`search`/`recall`/...)
  -> compose reply (D28; no separate translation step). (This is what `core` used to
  nominally do; it lives here now, D15.)
- **Turning requests into tool calls.** Given memory's MCP tools, the agent emits
  `recall` / `remember` calls directly via function-calling (no separate translator
  model; D28). A tool's `inputSchema` is the `QuerySpec` / `Assertion`; reference
  resolution ("my engine") happens in the `search` -> `recall` tool loop. See
  [memory-model.md](../memory/graph/memory-model.md) for the IR shapes.
- **Intent classification.** navigate / ask / state / act - itself a parse.
- **Role dispatch (the role registry).** agents is a set of prompted **roles**, each a
  `(system prompt + tool set + output schema + model tier)`. Dispatch is mechanical:
  `Task.intent` picks the role, `Task.complexity` picks the model tier (D22, D37). See
  **Roles** below.
- **The model wrapper + connection policy.** Every call goes through one wrapper to a
  **user-configured** connection that can reach an LLM: a local model, a separate
  inference server, a hosted API, a subscription-backed CLI, or anything else, chosen
  by configuration like any other adapter. agents does not care which. Cost, if any,
  is whatever that connection implies; nothing is billable unless the user configured
  a billable connection. One place to configure and audit.
- **Reasoning on demand.** Memory's study/conflict-resolution calls agents to
  reason over context; agents serve those requests (through the same configured
  connection).

## Roles (agents is a set of prompted roles, D37)

agents is not one prompt. A **role** = `(system prompt + tool set + output schema + model
tier)`; all roles share the one model wrapper, so the connection / never-surprise-billing
logic stays in a single place. Dispatch: `Task.intent` -> role, `Task.complexity` -> model
tier.

| Role | Job | Tools | Tier |
|---|---|---|---|
| **orchestrator** | take the utterance, route intent, run the recall loop, hit the D30 gate, compose the reply | `recall`, `search`, `remember`, `set_importance`, `activate`, `track_event`, `note_surfaced` | capable |
| **extractor** | pull facts into **structured** `remember` calls (`{entity, attribute, value, unit?, qualifier?, claim_type?, polarity, mode}`, D44/D46/D54); resolve ids + decide assert/update | `search`, `recall`, `remember` (D51e) | mid |
| **researcher** | resolve an open question with independent, authoritative evidence; deliver user-requested results | web search, fetch, `search`, `recall` (`nudge:false`), `remember`, `push` (results, D55c) | capable |
| **studier** | derive / check consistency / propose associations over a graph region; orchestrate **quiz sub-calls** and land resolutions with their earned `rigor`; run D48 meta-reviews | `recall` (`nudge:false`), `neighbors`, `remember`, `revise_question` (D56a) | capable |
| **quizzer** | adversarially refute a claim before it hardens (the self-test); a **sub-role**: runs as sub-calls inside the studier's task (D56b), verdict lands via the studier's `remember rigor:"quizzed"` | read-only (`recall` with `nudge:false`, D55e) | mid |
| **sentiment** | read the user's tone -> importance + reward-sign signals; a **sub-role**: invoked inline by the orchestrator during the turn (D56c), lands via `set_importance` / resolution fields | none | small/fast |
| **check-in** | gather due Events + top open Questions (D40), resolve what it can, escalate the rest to the user | `recall` (`nudge:false`, D57h), `search`, `remember`, `push` | mid |

**Dispatch map (D55b, amended by D56b/c):** `turn` -> orchestrator, `extract` -> extractor
(also runs inline in the turn; standalone for bulk ingestion), `research` -> researcher,
`study` -> studier, `check-in` -> check-in. **Quizzer and sentiment are sub-roles**, invoked
inside studier / orchestrator tasks respectively, never dispatched as standalone Tasks.
Every Task names one of the five dispatchable intents; there is no `parse`/`reason` intent.

The role registry (prompts + tool manifests + schemas) lives in `agents/` as assets. A
worker pulls a Task, loads the role for its intent, and runs it on the tier its complexity
picked.

### The agent's write-side decision list

On intake the orchestrator (and extractor) make exactly three decisions; the rest is
memory's bookkeeping:

1. **Route intent** - telling (`remember`) vs asking (`recall`) vs signaling relevance
   (`set_importance`) vs describing a pending real-world outcome (`track_event`, D39).
2. **Extract** - which claims in what was said are worth `remember`-ing.
3. **Gate (D30)** - after a recall, answer vs research vs ask.

Conversational intake runs the **extractor synchronously inside the turn**, so the
orchestrator receives `remember`'s ApplyResult flags and can narrate a surprise in the
moment ("wait, you told me 18 before"). D44's "off the hot path" means *memory's* hot
path (no model inside `remember`) and bulk/document ingestion, not the turn.

Every actual surfacing of a Question/Event to the user is stamped via `note_surfaced`
(D58j): agents **plumbing** stamps on interaction's `delivered(ref)` report (mechanical,
no model call, D59f), and the orchestrator stamps when the D30 gate asks inline (using
the Question refs `recall` returns, D59e). Ask-spacing keys on these stamps (D57e), so check-in never
re-asks what was recently surfaced; an inline ask is contextual to the user's own
utterance and needs no spacing check (D60). Check-in itself never stamps: a push-time
stamp would mark queued Prompts surfaced before delivery. agents also resolves every pushed ref
to its lineage head and stamps `Prompt.supersedes_ref` before pushing (D59g), so
interaction's queue dedup is plain id equality.

It also **follows up on Events** (D39/D40): when a tracked outcome's trigger fires (via the
study check-in), the agent surfaces the check ("did the cam caps hold?") through the
interaction `push` op; when the user answers (the `Utterance` carries `reply_to_ref`, D45),
the agent `remember`s the reported result, which mints a real-world Source and resolves the
linked Question/Event.

**Questions are memory's, not the agent's.** The agent never creates a Question; memory
mints them as a side effect of `recall` (a contest), `remember` (a contradiction, the
surprise detector lives there), and study. `remember` does double duty: store a claim
*and* feed/resolve any open Question its topic matches.

## Explicitly NOT responsible for

- Storing knowledge. Agents hold no graph state; they read/write it *through*
  memory's contract.
- Device I/O (audio, screen) - that's interaction.
- The write *policy* (capping, conflict checks) - that's memory's;
  agents hand it an `Assertion`, memory decides how it lands.

## Internal structure (current -> target)

| Now | Target |
|---|---|
| `enrich/llm.py` (current Claude SDK call; legacy subscription-only) | `agents/` model wrapper |
| `router.py` (intent classification) | `agents/` parse/route |
| recall orchestration in `knowledge/query.py` | `agents/` turn loop (calls memory) |
| `enrich/extractor.py` prompt-from-graph assembly | `agents/` (memory hands it the snapshot via the contract) |

## Speaks (contracts)

- [interaction <-> agents](../contracts/interaction-agents.md) — utterances in, replies out.
- [agents -> graph memory](../memory/graph/mcp.md) — recall/write via the graph
  memory's MCP tools (request/response).
- memory -> agents reasoning (study): an async job on the **queue plane**, not a
  contract here; see [../runtime-topology.md](../runtime-topology.md).

## Invariants (must always hold)

- Every model call goes through the one agents chokepoint to a user-configured
  connection (local model, inference server, hosted API, subscription-backed CLI, ...).
  Nothing is billable unless the user configured a billable connection; a user is
  never billed for a connection they did not set up.
- A failed/unavailable agent returns a typed failure, never a silent empty.
