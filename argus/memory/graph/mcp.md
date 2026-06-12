# Graph memory: MCP manifest (agents -> graph memory)

> Status: draft. The **graph** memory type's MCP server: the tools/resources the agent
> calls (D27, D29). memory is a set of typed MCP servers ([../design.md](../design.md));
> this is one of them. **agents is the host, the graph memory is an MCP server.** This
> is the **MCP plane** only (LLM-as-caller, request/response). The reverse direction
> (memory asking an agent to reason, e.g. study) is **not** here: it is an async job
> on the **queue plane**, see [../../runtime-topology.md](../../runtime-topology.md). Pattern
> and scope: [mcp-pattern.md](../../contracts/mcp-pattern.md).

## Shape

The graph memory runs as an **MCP server**; each agent (the host) connects as a client.
Because it is MCP, the transport is an adapter: stdio in-process / local, or HTTP/SSE
across machines, chosen by config (D18, D23). The agent calls memory's tools through
its native tool-use, so a tool's `inputSchema` **is** the query IR itself, there is no
separate QuerySpec-translation step (D27 amends D14).

`activate` sets the session's **focus** (the project the user is in), which **biases**
relevance *within that session* (it is not a global importance anchor, D55d), but the
graph is **global** (D41): recall, competence, study, and
importance propagation all operate over one graph, not a per-workspace partition. (Earlier
"each project is its own graph" isolation is dropped.)

memory's internals (graph / SQL / RAG) stay **private** behind this manifest. The tools
and resources are the only surface, so the implementation is swappable.

## Tools (operations the agent invokes)

### `recall`
Run a structured query: spread activation by **weight** (reachability), then rank the lit
candidates by **derived confidence**, discounted by attached Questions (D38). Returns
ranked facts with provenance. A claim with an incoming `supersedes` edge is **excluded
from ranking** (only chain heads compete; history stays reachable on request, D57d).
Traversal applies the **recall-time weight nudge** to the
returned candidates' paths while the session's activation is live (D53), unless the caller
passes `nudge: false` (background/adversarial roles, D55e); no separate feedback call
exists or is needed.
- **input** (this *is* the QuerySpec):
  `{ session_id: id, about: (name | id)[], attribute?: string, qualifier?: string,
     attested_by?: source-ref | "any", polarity?: +1 | -1 | "any",
     want: "value"|"fact"|"relationship"|"list", rank_by?: "confidence"|"recency",
     nudge?: bool }`
  (`session_id` because activation is per-session, D34/D51f; `qualifier` so a qualified spec
  can be asked for, "the cold-engine torque"; `nudge` defaults true, and adversarial /
  self-directed roles pass false so study walking the graph does not wear paths like real
  use, D55e.)
- **output:** `{ found: bool, results: RankedFact[], questions?: id[] }` where `RankedFact` =
  `{ fact, confidence, effective_confidence, activation, attestations[] }` (D54d:
  `confidence` is the raw derived value, attestations × source competence, D38;
  `effective_confidence` is after the Question discount and is what the D30 gate reads;
  `activation` is the per-session reachability the spread computed for this result,
  replacing the old per-fact `weight`, which lives on links, D38; attestations give
  provenance; `questions` = the open Questions attached to the returned candidates or
  minted by this recall, D59e: the refs the orchestrator needs for `note_surfaced` on an
  inline ask; the user's eventual answer resolves via `remember`'s structural
  topic-match, no ref carried across the turn boundary, D60d)

### `remember`
Apply an assertion: create immutable claim/association nodes + an attestation with
inferred polarity. memory enforces its write policy (conflict checks; machine-sourced
claims land immediately but *quiet*: their Source's competence is capped, so derived
confidence is capped until validated, never write-staged, D53). Append-only. **Double duty (D35/D37/D43):** `remember` also detects a
**surprise** *structurally* (the complement of the match key, D60a: same
entity/attribute/qualifier, different `(value, unit)` or polarity, vs an existing
high-confidence claim, no model on the hot path) and mints a Question (searching for an
existing one first, dedup), and it **feeds/resolves** any open Question whose topic the
claim matches. Questions are minted by memory here and in `recall`/study, never created by
the agent (no `create_question` tool by design; the narrow exception is
`revise_question`, D56a: study's meta-review may rework an existing Question, never
create one from scratch).
- **input** (a **structured** claim, D44/D46/D51/D54, the agent supplies it):
  `{ entity: name | id, attribute: string, value: scalar | name | id, unit?: string,
     qualifier?: string, claim_type?: "empirical" | "derivable",
     polarity: +1 | -1, mode: "assert" | "update",
     supersedes?: claim-id, resolves_ref?: question-id | event-id,
     source: source-ref,
     source_type?: "user"|"manual"|"paper"|"experiment"|"web"|"forum"|"machine",
     via?: "machine",
     rigor?: "read-one"|"cross-checked"|"quizzed",
     text?: string }`
  (`entity`/`value` are **name-or-id**, memory match-or-creates (D51); `source` is likewise
  **name-or-id** with the same match-or-create semantics, so the user / a manual stays ONE
  Source node across sessions (competence needs stable identity, D54e); `source_type` is
  agent-supplied and consumed only when the Source is first **created** (it sets D42's
  born-from-type competence prior; omitted/unknown -> low prior; memory cannot classify,
  D55a); `via:"machine"` marks a machine-extracted attestation (the extractor sets it on
  every bulk-ingestion write): `source` stays the document, but the attestation contributes
  at most `cap_provisional` until validated (extraction fidelity is not document
  reliability, D57c); `rigor` is valid with `resolves_ref` and is how a resolving agent reports the
  earned ladder rung ("survived adversarial quizzing"), scaling the resolution's
  uncertainty drop; self-earned resolutions stay capped at `cap_provisional` regardless
  (D56b); `qualifier` holds
  conditions ("when cold"); `claim_type` (stored on the claim, **default empirical**) drives
  the quality-ladder fork and the D49 user guard (D53/D54a); `mode:assert` can trip surprise
  only against a high-confidence claim of the **same qualifier**; `mode:update` supersedes
  the prior value as a state change *unless* it contradicts a high-confidence
  non-user-attested claim, then it mints a low-urgency Question instead of silently
  overwriting (D51c). `resolves_ref` closes the Question/Event a proactive answer was about
  (D51e); it follows a supersedes chain to the lineage head, and for a decomposed target
  applies to the child whose key the claim matches (D58e). An identical existing claim (key incl. `unit`, D59b) is
  **attested, not duplicated** (claim-level match-or-create, D58h), and attestation is
  **idempotent**: one per `(source, claim, polarity, via)`, a repeat refreshes timestamps
  only, a direct attestation **supersedes** its via-machine twin rather than adding
  (one origin, one contribution, D60c), and an opposite-polarity attestation from the
  same `(source, via)` **supersedes** the prior one (a source can retract; latest polarity
  wins per origin, D62a), so repetition never raises truth (D59a) and retraction never
  self-cancels. `text` is the original
  phrasing.)
- **output:** `ApplyResult` —
  `{ surprise?: bool, question_minted?: id, question_resolved?: id,
     supersession_refused?: bool }` (flags so the orchestrator can narrate what the call
  triggered, D50. There is no `status` field, D54c: append-only means every accepted write
  is applied; a conflict shows up as `surprise`/`question_minted`, a refused supersession
  (D51c) as `supersession_refused`. `staged` was dropped earlier by D53.)
  Confidence is **lazily derived** from live competence at read time, so a resolution needs no
  write-back cascade (D51a).

### `search`
Fuzzy / full-text lookup to resolve a name or phrase to entities or facts (the entry
points for `recall`).
- **input:** `{ text: string, kind?: "entity"|"fact"|"source", limit?: int }`
  (`source` resolves a source name ("the Haynes manual") to a Source id, e.g. for
  `attested_by`; the old `doc` kind left with the RAG fallback, a future `rag/` memory
  type's job, D29.)
- **output:** `Candidate[]` — `{ id, label, kind, score }`

### `neighbors`
Step the graph: the weighted neighbors of an entity.
- **input:** `{ id: string, relation?: string, limit?: int }`
- **output:** `Edge[]` — `{ from, to, relation, weight }`
  (Plain associations carry no relation label; `relation` matches only the labeled
  structural edges, `IS-A` / `supersedes`. Domain relationships are claims with
  entity-ref values, D44, reached via `recall`, not here.)

### `activate`
Set the session **focus** (one global graph, D41/D50): open a project ("open project
cressida") or note a mention that shifts focus. A **seed that biases** recall ranking
within this session, not a partition and not a global importance anchor (D55d): one
session opening a project must not shove another session's rankings.
- **input:** `{ session_id: id, focus?: string, hint?: string }`
  (`session_id` because focus is **per-session** working memory (D34) and pooled workers
  share MCP connections (D21), so focus is an explicit argument, never connection-bound
  state, D53.)
- **output:** `{ active_focus: id }` (the resolved focus seed; the old
  workspace-list-shaped output is gone with partitions, there is nothing to enumerate
  over one global graph, D41)

### `set_importance`
Set/raise/archive an **importance anchor** on a node (D36), separate from `remember`. The
agent maps relevance statements onto this ("this is critical" -> raise; "I sold the X /
forget X" -> archive). memory re-propagates importance from the changed anchor, cooling
only what depended on it.
- **input:** `{ target: id, op: "raise"|"set"|"archive", level?: 0..1 }`
- **output:** `{ ok, repropagated: int }`

### `track_event`
Record a **pending real-world outcome** to follow up on (D39): an experiment, a delivery, a
job in progress. The agent calls this when the user describes something in flight. memory
mints an Event node with a follow-up trigger; the study clock fires due follow-ups, and the
reported outcome mints a real-world Source that resolves the linked Question.
- **input:** `{ what: string, check: string, trigger: { at?: time, when?: context },
  resolves?: question-id[], about: (name | id)[] }`
  (`about` entries are name-or-id, match-or-created like `remember`'s `entity`, D51e/D57h,
  so an Event's links never dangle on unresolved names.)
- **output:** `{ event_id }`

### `revise_question`
The **one agent-side Question write** (D56a), usable only by study's meta-review (D48):
rework a stale Question that study handed over. **Reframe** mints a better-posed Question
that supersedes the old one (so the user is never asked a badly-posed question);
**decompose** splits it into smaller child Questions (parent/child links; resolving the
parts answers or dissolves the parent); **park** shelves it (awaiting the user / the
world, D57a); **resume** un-parks it (D58b); **abandon** closes it unresolved. Does not break
D35: memory still mints all Questions; the agent can only rework, never create from
scratch.
- **input:** `{ question_id: id,
  action: "reframe" | "decompose" | "park" | "resume" | "abandon",
  replacement?: { entity, attribute, qualifier?, text },
  parts?: { entity, attribute, qualifier?, text }[] }`
  (`replacement` for reframe; `parts` for decompose, one per child Question. The claim-key
  shape keeps revised Questions visible to structural dedup, topic-match, and discounting,
  D57g; memory wires them to the parent's candidate/about edges **partitioned on
  `{entity, attribute}`** (qualifier discriminates only when the candidate carries one,
  D61a): an unqualified candidate splits its weight among all children sharing its key; a
  qualified candidate goes only to the qualifier-equal child; unmatched candidates move to
  an automatic **remainder child** carrying the parent's key, abandonable if moot (D61b). **Park**
  (D57a): the Question awaits the user / the world, exempt from study dispatch and
  ask-spacing pressure, still alive and discounting. Revisions inherit the lineage's
  attempt count against D47's cap; past the cap, only park or abandon. Parent/child:
  parent uncertainty = max of open children; the parent closes when all children close, or
  sooner if a child's resolution structurally answers the parent's key (open siblings then
  close-as-moot, D59d). **Reframe closes
  the old Question as superseded**: it stops discounting, is invisible to dedup, and no
  longer blocks GC; only lineage heads count (D58e). **Resume** un-parks (D58b); study may
  also resume a parked Question when new evidence touches its candidates.)
- **output:** `{ ok, new_question_ids?: id[] }` (the superseding Question, or the children)

### `note_surfaced`
Stamp a Question/Event as **actually surfaced to the user** (D58j): agents calls this when
interaction reports a `push(Prompt)` delivery, and when the orchestrator asks inline during
a turn (the D30 gate's "ask"). Ask-spacing keys on this stamp (D57e), so the user is never
re-asked minutes after an inline ask.
- **input:** `{ ref: question-id | event-id }`
- **output:** `{ ok }` (idempotent)

## Resources (addressable read-only data the host reads)

- `memory://snapshot?focus={id}` — a projection of the graph for context (entities, facts,
  edges with their weight); `focus` **filters/biases**, it does not partition (D41/D45).
- `memory://source/{id}` — one Source node: its type, competence, and the claims it
  attests. (Replaces the old `memory://doc/{id}`: raw document text belongs to a future
  `rag/` memory type, not the graph, D29.)
- `memory://entity/{id}` — one entity with its facts and attestations.

Resources are read-only; **all writes go through `remember`**, so the write policy is
never bypassed.

## Guarantees

- Answers carry provenance + derived confidence; focus biases relevance but the graph is global (D41);
  writes are append-only and policy-checked; the graph stays inspectable.
- The tool/resource manifest is the whole surface; memory's storage is private and
  swappable behind it.

## Errors (returned as MCP results / tool errors, not exceptions across the edge)

- Store unreachable -> a typed `MemoryUnavailable` tool error (not a silent empty).
- A conflicting `remember` is **not an error and not rejected**: the claim is applied
  (append-only, D10) and the conflict is reported via the `surprise` /
  `question_minted` flags (D54c).
- A query that resolves nothing -> an empty result with `found: false`, not an error.

## Not in this contract

- **memory -> agents reasoning** (study, conflict adjudication, doc extraction): the
  agent is the callee there, not the caller, so it is **not** MCP (D27). It is an async
  **job on the queue** (a background `Task`, intent `study` or `research`, D55b); see
  [../../runtime-topology.md](../../runtime-topology.md).

## Versioning / open questions

- Tool/resource schema evolution: the manifest is the boundary, version it explicitly.
- ~~Whether `activate`/focus is per-session state on the MCP connection or an explicit
  argument~~ **Resolved (D53): an explicit `session_id` argument** (pooled workers share
  connections, D21/D34). Session identity itself (lifetime, boundaries) stays open.
