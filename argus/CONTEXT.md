# Argus, design handoff context

Dense briefing for a fresh Claude picking up the design. **Nothing is built yet**, this is
all design. Canonical truth lives in the docs under `argus/` (this file summarizes; when in
doubt, the linked docs win). Decision log is the spine: `argus/architecture.md` (newest
first, D1-D60, with supersede/amend notes).

Project conventions: append-only decision log (never rewrite history, add a new dated
decision that supersedes). Docs live **next to the system they describe** (no `docs/`
folder). Plain, human naming. **No em dashes anywhere** (user rule, use commas/colons/
parens). The "garage / 2JZ / torque spec" stuff is a running *example*, not the system's
focus.

---

## What Argus is

An AI system made of separate **systems** that talk only through **contracts** (fixed,
serializable messages). Today three; more can be added later via their own contracts.

- **interaction** - the user I/O channel (input + output; speech, text, later more). Pure
  I/O, no logic. Speech-to-text lives here. NOT world-perception (that would be a future
  `sensors` system) and NOT physical action (`actuators`).
- **agents** - the thinking executive. Routes intent, makes all model calls (one wrapper),
  composes replies. Has **no loop of its own**; only acts when handed a Task.
- **memory** - stores and recalls what is known. A set of **typed MCP servers** (graph
  type first); swap type = different MCP. Holds per-session conversational focus.

Two initiators, one responder: **interaction** starts on input, **memory** starts on a
clock (the study loop), **agents** only responds. Each system is its own process;
placement (same machine / datacenter / storage server) is configuration. Contracts are
transport-agnostic (in-proc / socket / network RPC = adapter swap).

---

## Runtime / topology (see `argus/runtime-topology.md`)

- **Contracts:** interaction<->agents (front door), agents->graph-memory (MCP),
  memory<->interaction (notifications/live-view, deferred). New systems add their own.
- **Three planes:** **MCP** (sync, LLM-as-caller, request/response: agent->memory and
  future agent->tools/actuators), **queue** (async jobs: background tasks, memory->agent
  reasoning), **stream** (continuous no-LLM data: future sensor ingest). Front door is its
  own thing.
- **Tasks:** every agent job is a `Task {id, mode, reply_to?, complexity 0-9, intent,
  context, schema?, budget?}` (budget = D47's token/time bound). `mode` = **interactive** (someone waiting, reserved capacity, direct
  request/reply) or **background** (queue, fire-and-forget). `intent` -> agent role;
  `complexity` -> model tier.
- **Queue** = ingress to the background agent pool (NATS planned; local now, WAN later).
  memory is NOT queue-fed (it is a request/reply authority). Reserved capacity for
  interactive so background can never starve it.
- **Two research lanes (strict priority):** user-requested research first, self-directed
  study on the slack (small/preemptible). Curiosity is never intrusive.
- **Model connection** is user-configured (D25): local model / inference server / hosted
  API / subscription CLI / anything. One chokepoint; nothing billable unless the user
  configured a billable connection. MCP requires a **tool-capable** connection (D27).

---

## agents internals (see `argus/agents/design.md`, D37)

agents is a **role registry**. A role = `(system prompt + tool set + output schema + model
tier)` over the one shared model wrapper. Dispatch: `Task.intent` -> role,
`Task.complexity` -> tier. Roles: **orchestrator** (turn-taker), **extractor** (what to
remember), **researcher**, **studier**, **quizzer** (adversarial self-test), **sentiment**
(tone -> importance + reward sign), **check-in** (gathers due Events + top Questions,
escalates via `push`, D55b).

Agent write-side decisions are only three: **route intent** (tell=`remember` /
ask=`recall` / relevance=`set_importance`), **extract** (which claims to remember), **gate
(D30)** (answer / research / ask). **Questions are memory-minted, not agent-called.**

agents <-> memory uses **MCP** (D27): the agent emits `recall`/`remember` tool calls
directly via native function-calling (no separate translator; D28). A tool's inputSchema
IS the query IR. Reference resolution ("my engine") happens in the `search`->`recall`
loop.

---

## The memory graph model (the heart, see `memory/graph/memory-model.md` + `lifecycle.md`)

**Three values, not one** (un-fused, D38, supersedes the fused D31): **weight** (stored, on
association links, reachability, use-driven, drives spreading), **confidence** (*derived*
per claim = `squash(Σ independent competence × polarity)`, never stored, so use cannot
move it), **competence** (stored, on sources, trust/track-record, validation-driven). The
fusion failed because *use* would then raise confidence (popularity -> truth); keeping them
separate gives relevance-from-use AND honest confidence, plus free retroactive correction
(fix a source -> all its claims re-rate). Reward has **two channels**: use -> weight
(nudged **at recall time** on the returned paths, no feedback op or retained trail, D53);
validation -> mint-source + competence -> re-derived confidence. Magnitude ~ **prediction
error**. Reward ladder is **claim-type-dependent** (D53): real-world result always top;
on empirical claims competent-user-confirmed > studied, on derivable claims studied >
user opinion; then read-one-source > mere-acceptance; correction/ridicule punish; decay
forgets. **The weighting is the experiment.**

**Recall** is two-stage: **spread by weight** (reachability, find candidates) then **rank
by derived confidence** (truth, pick), discounted by attached Questions. Budgeted (worn
paths first; cold may not be reached). Activation is transient per-session scratch (D34,
never on the shared graph, so concurrent sessions never collide). Structure does identity
(entities + inheritance, instance-overrides-type); weight does relevance; confidence does
truth.

**Questions** (node type) are the home of uncertainty AND the unit of the reward loop. One
structure, four jobs: eligibility, curiosity target, proactive-question source, resolution
provenance. Born when uncertainty is salient: contested recall / weak / gap (at recall),
**surprise** = new claim contradicts a confident belief (at intake, detector lives in
`remember`), or study finds a latent gap. A Question is a snapshot of the contested recall:
connects to **candidates** (edge weight ~1), their **sources** (~0.2), **topic** seeds
(~0); carries **uncertainty** and inherits **importance**. Recall discounts a claim by
`Σ uncertainty(Q) × weight(Q->claim)` (contested facts come back quiet -> trips the gate).
**Reward = resolving a Question structurally:** evidence lowers uncertainty, **mints a
Source node** for whatever settled it (experiment/research/user) attesting the winner
(raises its *derived* confidence; the graph grows its own evidence), updates source
competence, and nudges the used weights. Close at uncertainty < ε; goes cold but kept
(provenance). Salience is **emergent** (cheap
to create, decay prunes one-offs, recurrence + importance keep the rest warm), no tuned
creation threshold.

**Events** (node type, D39) = pending real-world outcomes to follow up on (an experiment, a
delivery, a job in progress). **Agent-created** at intake (vs Questions, memory-minted),
carry what-to-check + a follow-up trigger (time/context) + links to the Question they would
resolve. The study clock fires due follow-ups; the agent asks "did it work?"; the reported
outcome **mints a real-world Source** (top of the ladder), resolves the linked Question,
delivers strong reward. They are how the best reward signal actually flows (without
follow-up it evaporates). Sibling of Questions (internal-uncertainty vs external-pending;
memory-minted vs agent-created; resolved-by-seeking vs resolved-by-following-up). Op
`track_event`.

**Importance** = attention, a node value distinct from weight/confidence (truth). Selling
the Cressida drops importance, not truth. **Anchored + propagated**: a few anchors (user,
painful-error/stakes, **sentiment agent**; NOT session focus, D55d) and importance flows across
associations. Context events re-anchor immediately ("this is critical" raises; "I sold the
X / forget X" archives) and re-propagation cools only what *depended* on the anchor (shared
knowledge survives). Drives study priority (`uncertainty × importance`) and decay rate
(important decays slower). Not a one-way ratchet. Agent maps relevance statements to a
`set_importance` directive.

**Append-only** (D10): claims immutable; a disagreeing value is a new node, the old goes
cold but kept. Claim content never changes; confidence is
derived; outside claim content the stored moving values are weight (links), competence
(sources), importance, and the Question/Event scalars. Reads lock-free.

**Study** (renamed from "dreaming", D33): memory's clock loop. Walks open Questions by
`uncertainty × importance`, researches + self-tests (derivations, independent cross-checks,
other agents quizzing it), resolves provisionally (below ground truth), banks the rest as
questions for the user, plus housekeeping (decay, prune cold+unimportant).

**User is a topic-dependent source, not ground truth** (D32, anti-sycophant): weighted by
inferred per-topic competence; Argus questions the user when input conflicts with studied
knowledge; real-world results outrank opinion.

**Values** (full mechanics in `lifecycle.md`): weight (links, reachability), confidence
(derived per claim, truth), competence (sources, trust), uncertainty (Question), importance
(node), edge weight (Question edges), Event trigger/status, activation (transient
per-session).

---

## File map (everything under `argus/`)

```
system_goal.txt            whole-system charter (plain language)
architecture.md            master design + decision log D1-D60 (the spine)
runtime-topology.md        processes, tasks, queue, scaling, two research lanes
architecture.drawio        3-page diagram (compartments, task routing, scaling)
CONTEXT.md                 this file
interaction/  system_goal.txt + design.md
agents/       system_goal.txt + design.md (role registry)
memory/       system_goal.txt + design.md (typed-MCP container)
  graph/      design.md + memory-model.md (the model) + lifecycle.md (mechanics) + mcp.md (tools)
contracts/    interaction-agents.md, memory-interaction.md, mcp-pattern.md
```
(Existing code still has the OLD layout: `store/ knowledge/ enrich/ workspace/`. The D1
file-move into `interaction/ agents/ memory/` has NOT happened, only the design dirs +
docs exist.)

---

## Key decisions (active; one-liners; full text in architecture.md)

D1 three compartments (->interaction/agents/memory). D3 contracts transport-agnostic. D5
one model wrapper. D8 Hebbian-symbolic + inspectable (kept). D10 append-only knowledge. D11
user high-but-not-absolute. D13 one node type Fact, association+attestation edges (refined
by D31/D35). D14 NL<->graph (amended by D28). D15 no `core`; folded into agents/memory
(amended by D26/D34). D18 separate processes; location=config. D19 two initiators / one
responder. D20 all agent work is a Task; interactive vs background. D21 queue feeds
background agent pool; memory request/reply; reserved interactive capacity. D22 background
routed by complexity->model. D23 placement symmetric; resilience by placement. D24 NATS,
mTLS, strict reservation, complexity rubric. D25 model connection user-configured (not
subscription-locked). D26 HID->interaction; user channel; sensors/actuators future; systems
open-ended. D27 agent->system req/resp = MCP (agents host, systems are MCP servers). D28
agent emits tool calls directly (no translator model). D29 memory = typed MCP servers
(graph first). D30 research first, ask user last. D31 ONE fused strength (SUPERSEDED by
D38). D32 user = topic-dependent source, not a sycophant. D33 dreaming -> study; curiosity,
self-test, two research lanes. D34 focus = per-session working memory (not global). D35
uncertainty+reward live as Question nodes. D36 importance = anchored attention value,
distinct from truth. D37 agents = role registry; dispatch by intent+complexity. D38
UN-FUSE: weight (reachability, links, use-driven) + confidence (derived per claim) +
competence (sources, validation-driven); restores D9/D12, supersedes D31. D39 Event nodes:
pending real-world outcomes, agent-created, follow-up mints a real-world Source. D40
proactive user contact: study check-in loop gathers due Events + open Questions -> agent ->
`push` op to user (live-now else queue-next); amends D19. D41 ONE global graph (drop
workspace isolation; workspace = focus/importance seed). D42 competence born from source
type (manual/paper high, user med, forum low) + self-tune; this IS cold-start confidence;
independence via priors + research-agent judgment (structural lineage punted). D43
reward/Question mechanics: structural surprise in `remember` (semantic later); conflict =
Question only (no double-count); Question dedup (search-before-create); snapshot
answered-confidence for prediction-error. D44 KEYSTONE: structured claims at the
remember/Question boundary `{entity, attribute, value, unit?, polarity}` (agent supplies),
so surprise/dedup/topic-match run structurally with no model; `value` may be scalar or
entity-ref. D45 contract/formula fixes (2nd review): `Utterance.reply_to_ref` (proactive
answer routing), global resource URIs (`memory://entity/{id}`), discount clamped [0,1],
squash=tanh, prediction snapshot = raw committed-answer confidence (prior-belief for
surprise), proactive push runs as its own session seeded from the Event's entity. D46 claim
shape extended `{...,qualifier?}` + `mode:assert|update` + `supersedes` (state-change vs
conflict; DEEPLY NOTED as the top rework risk). D47 bound the study/background layer
(token/time budget per bg task + idle backoff + research depth cap). D48 Question
**freshness**: rots -> agent meta-review (reframe / decompose / delete) + light ask-spacing;
Questions gain reframe/decompose links. D49 user = competence special case (floored; demoted
only by real-world/authority on empirical claims). D50 round-3 fixes: `remember` returns
{surprise,question_minted,question_resolved}; competence cascade off hot path; superseded
claims GC-eligible regardless of importance; fossils fixed (D15 body, `activate`
workspace->focus, drop notify(kind:question)). D51 round-4 corrections (UNDO over-patch):
confidence stays lazily derived (revert D50b cascade); freshness = derived stalled-attempt
counter (not stored); `mode:update` mints a Question if it contradicts a high-confidence
non-user claim (no silent-overwrite, amends D10); GC keeps attestation stubs; cold-start =
tanh(Σ), competence in [0,1] (drop "= competence"); remember `entity` name-or-id +
`resolves_ref` (closes Event/Question) + extractor gets search/recall; recall gets
`session_id`; fossils (D36 weight, context-triggers deferred). D52 Stage-1 scope: ON =
structured remember + spread-by-weight + rank-by-tanh-confidence + ONE competence scalar +
structural surprise/dedup + Questions/Events + bounded study; OFF/deferred = mode:update
supersession & superseded-GC (behave as assert), decompose, per-topic competence,
context-triggers, NATS/mTLS/pool/WAN. D53 round-5 consistency: quality ladder forks by
claim type (empirical: competent-user > studied; derivable: studied > user opinion);
good-use weight nudge applied at recall time while activation is live (no feedback op, no
retained trail; down = decay + Question-resolution against a losing candidate);
write-staging superseded (machine claims apply immediately but quiet, capped Source
competence -> capped derived confidence; supersedes the staged-enrichment hard rule;
`remember` statuses = applied|conflict); `activate` gains `session_id` (focus is an
explicit argument, never connection-bound); fossils fixed; noted: single-source confidence
ceilings at tanh(1) ≈ 0.76, so high-confidence bars must sit below it. D54 round-6 carriers:
claims gain `claim_type` empirical|derivable (extractor-supplied, default empirical; drives
the ladder fork + D49 guard); recall-born Question snapshot = top-ranked candidate's raw
confidence at mint, and resolution magnitudes scale by prediction error (snapshot finally
consumed); `remember` drops `status` (flags only, + `supersession_refused` for the D51c
case); `recall` returns `{found, results[{fact, confidence, effective_confidence,
activation, attestations}]}` (the D30 gate reads `effective_confidence`); `source` is
name-or-id match-or-create like `entity` (stable Source identity, or competence scatters);
plus another artifact sweep (doc/RAG leftovers out of the MCP manifest, workspace-shaped
`activate` output gone, pre-D38 hard-rule phrasing fixed). D55 round-7 carriers (from six
end-to-end scenario traces; four traced clean): `source_type` on `remember`
(user|manual|paper|experiment|web|forum|machine, set at Source creation, feeds D42's
competence prior); intent->role map pinned (turn/extract/research/study/quiz/sentiment/
check-in) + new **check-in** role owning D40's loop and `push`; user-requested research
results delivered via `push(Prompt{kind:"result"})` (background stays fire-and-forget);
focus is NOT a global importance anchor (pre-D34 artifact; focus biases its own session
only, amends D36); `recall` gains `nudge?` (background/adversarial recalls don't wear
paths); Task gains `budget` (D47); freshness attempts stamped at dispatch; Event
resolution = one attestation (no double-count); surprise closes same-step only if the
minting evidence clears ε; extractor runs synchronously inside the turn. D56 round-8
closures: `revise_question` (reframe | decompose | abandon; the ONE agent-side Question
write, meta-review only; decompose op exists from the start, narrowing D52); quizzing =
sub-calls inside the studier's task + `remember` gains `rigor` (read-one | cross-checked |
quizzed, the carrier for the studied ladder rung); sentiment invoked inline by the
orchestrator (quizzer + sentiment are sub-roles, not dispatch targets); GC guard (a node
referenced by an open Question/Event is never pruned); `push` = the front door's reverse
direction, not MCP; plus a decision-log marker sweep (ten headers gained forward pointers).
D57 round-9 closures (runtime-pathology hunt): revision lineage capped (children inherit
attempts vs D47's cap) + **park** action (awaiting user/world: exempt from study +
ask-spacing, still alive/discounting; ask-spacing never resets across revisions);
one-attestation rule on Question resolution (the resolving remember's attestation IS it;
no double-count; user stays one Source); machine-extraction cap (`via:"machine"` on the
attestation, contributes ≤ cap_provisional until validated; source stays the document);
supersession enforced at read (only chain heads ranked; supersedes-edge write un-deferred
for Stage 1); ask-spacing keys on a last-surfaced-to-user stamp (actual Prompt delivery,
not research attempts); snapshot complete (gap/study-born = 0, reframe inherits, decompose
re-snapshots; outcome = 1 confirmed / 0 overturned); revise_question structural
({entity, attribute, text} parts, wired to parent edges; parent uncertainty = max of open
children); decay floor dial; uncertainty ∈ [0,1]; check-in/researcher recalls nudge:false;
queued Prompt dedup by ref; track_event about = name-or-id. D58 composition fixes (from
the targeted Question-lifecycle re-trace): snapshot = pair {presumptive claim-id|none,
confidence} (outcome compares identities; gap/study-born = {none,0}, outcome 1); park
reversible (`resume` action; study resumes when new evidence touches candidates); decompose
children born with parent's uncertainty + {none,0} snapshot (re-derived at first recall);
parent stops discounting on decompose (children carry it; parent = bookkeeping, closes
silently, no own §5 run); reframed Question = closed-as-superseded (only lineage heads
discount/dedup/surface/block-GC); resolves_ref + queued-Prompt dedup follow the chain to
the lineage head; involved set frozen at mint excluding the resolver's own attestation (no
self-boost); closed-Question dedup match creates the reopens edge; claim-level
match-or-create on {entity, attribute, value, qualifier}; attempts stamp on any dispatch
(both lanes); `note_surfaced` op stamps actual surfacings (push delivery + inline asks).
D59 round-10 closures: attestation idempotent (one per (source, claim, polarity, via);
repetition NEVER raises truth); `unit` joins the claim match key (18 Nm is not 18 ft-lb);
decompose partitions the parent's candidate edges by key match (no child-count discount
multiplication); early parent close kept, open siblings close-as-moot; `recall` returns
`questions?: id[]` (refs for inline-ask note_surfaced + next-turn resolves_ref);
`delivered(ref)` op on interaction->agents (queued-Prompt delivery report, handled by
agents plumbing, no model); agents resolves pushed refs to lineage heads +
`Prompt.supersedes_ref` (interaction dedups by plain id equality); tool enumerations and
markers swept. D60 round-11 closures: surprise/conflict test = complement of the match key
(same entity+attribute+qualifier, different (value, unit) or polarity: 18 Nm vs 18 ft-lb
IS a conflict); decompose boundaries (unmatched candidates stay on the parent at ~1;
same-key children split the weight; parts gain qualifier?); cross-via collapse (a direct
attestation supersedes its via-machine twin, one origin one contribution); inline-ask
answers resolve via topic-match (no cross-turn ref; D59e's claim corrected);
direct-parent resolution = the D59d early close; check-in loses note_surfaced (plumbing +
orchestrator are the only stampers); delivered() stamps Question/Event refs only.

Superseded: D2, D6, D7 (mesh/leaf/core), D31 (-> D38), workspace-isolation hard rule (->
D41), D50b cascade (-> D51a). (D9/D12 superseded by D31, then restored by D38.)

---

## Open / next (what we were about to work on)

**FOUR design reviews run and resolved** (-> D38-D52). The design has **converged** (each
round's findings had smaller blast radius; round 3 over-patched and round 4 walked it back).
A **fifth consistency pass** (2026-06-11, -> D53) reconciled the quality ladder (forks by
claim type), wired the good-use weight nudge to recall time, superseded write-staging, and
fixed fossils; a **sixth, fresh-context pass** (2026-06-11, -> D54) swept remaining
artifacts and pinned five missing carriers (claim type, snapshot semantics, the
remember/recall schemas, source identity); a **seventh pass** (2026-06-11, -> D55) traced
six end-to-end scenarios (four clean) and pinned carriers (source type, the intent->role
map, research delivery, focus-vs-importance, the nudge flag); an **eighth pass**
(2026-06-11, -> D56) audited the D53-D55 patches, the log chain, and six new traces, and
closed the agent-side periphery (revise_question, quiz/rigor, inline sentiment, the GC
guard, push classified); a **ninth pass** (2026-06-11, -> D57) hunted runtime pathologies
and closed the Question-lifecycle defects (revision loop, double attestation, the
extraction cap hole, read-time supersession, ask-spacing starvation). The memory model has
held four straight rounds. The **targeted Question-lifecycle re-trace** then ran (-> D58):
the core path was buildable with two cross-cutting fixes (snapshot pair, frozen involved
set) and the D57 revision machinery needed composition rules (reframe closes-as-superseded,
single-discount decompose, reversible park, chain-following refs, the reopens edge,
claim-level match-or-create, `note_surfaced`); all applied. The loop now runs **fresh review rounds until one comes back clean** (user
directive): round 10 audited D58 and produced D59 (idempotent attestation, the unit key,
partitioned decompose, recall question refs, delivered(ref), lineage-head dedup at
agents); round 11 audited D59 and produced D60 (unit-aware surprise, decompose boundary
rules, cross-via collapse, topic-match for inline answers). After the clean round: the
stage/milestone restructure (agreed in principle, pending), then plan the build. Verdict: architecture sound and buildable;
the remaining softness is the claim write-path (qualifier matching, "topic",
spreading-activation algorithm) which **hardens against real data, not another review**.
**Next time online: plan the Stage-1 build.**

Standing open (Stage-1 spec / research bets, not contradictions): the **spreading-activation
algorithm** (budget unit, fan-out/hub normalization, cycle handling, lit threshold, `squash`
= tanh); **entity resolution** (match-or-create on `entity` name + alias/coref edge, since
append-only can't merge); **session identity** (load-bearing for focus + push + recall
activation, must be pinned); **qualifier match semantics**; the **sentiment-magnitude
carrier** (how ridicule/emphasis reaches a resolution, decide at Stage-1 step 3, D53);
**importance bookkeeping** (per-anchor contributions vs full re-propagation, D53);
**budget exhaustion semantics** (who enforces the Task budget; what a mid-task kill does
with partial findings, decide at build, D57); tuning
numbers; and the deepest,
**is the weight+derived-confidence self-tuning model viable** (only the build settles it).

Build order (agreed): Stage 1 = one process, static recall baseline first (spread by weight,
rank by confidence), then turn on the reward/study layer and *measure*; local queue now, WAN
later; do not write NATS/mTLS/pool until there is a second machine.

To get oriented fast: read `architecture.md` decision log, then
`memory/graph/memory-model.md` + `lifecycle.md`, then `agents/design.md`.
