# Argus architecture (master)

This is the source of truth for **how Argus is structured and why**. It tracks
the compartments, the contracts between them, and the decision log. When a
structural decision is made, it gets an entry here before code changes.

> User-facing setup and commands live in the root `README.md` and `CLAUDE.md`.
> This file is about the shape of the system, not how to run it.

## Status (2026-06-08)

**This is design, not yet built.** The existing code still has the old layout
(`store/ knowledge/ enrich/ workspace/`); the systems, contracts, and memory model
below are the agreed target, captured in decisions **D1-D64**. The system directories
now exist (`interaction/ agents/ memory/`, each with a plain-language `system_goal.txt`
and a `design.md`, plus `contracts/` and this doc). The D1 file-move was **started by an
outside tool** (2026-06-11, unreviewed WIP: old layout deleted; a simple CLI +
orchestrator under the new dirs); review before building on it.

**Four design reviews run and resolved (D38-D52); the design has converged and Stage-1 scope
is set (D52). Next is building the static-recall baseline, not more design.**

**(2026-06-11) A fifth consistency pass produced D53:** the quality ladder forked by claim
type, the good-use weight nudge moved to recall time, write-staging superseded, `activate`
gains `session_id`, fossils fixed. **A sixth, fresh-context pass produced D54:** five
missing carriers pinned (claim type, snapshot semantics, the remember/recall schemas,
source identity) plus another artifact sweep. **A seventh pass traced six end-to-end
scenarios and produced D55** (source type, the intent->role map, research delivery,
focus-vs-importance, the nudge flag). **An eighth pass audited D53-D55, the log chain, and
six new traces, producing D56** (revise_question, quiz-as-subcall + rigor, inline
sentiment, the GC guard, push classified) plus a marker sweep. **A ninth pass hunted
runtime pathologies and produced D57** (revision-lineage cap + parked Questions, the
one-attestation resolution rule, the via-machine extraction cap, read-time supersession,
ask-spacing on actual surfacings, complete snapshot/outcome semantics, structural
revise_question). **A targeted Question-lifecycle re-trace then produced D58** (snapshot
pair, reversible park, child uncertainty, single-discount decompose, Question-side
supersession, frozen involved set, the reopens edge, claim-level match-or-create,
`note_surfaced`): the revision machinery now composes end to end. **Round 10 audited D58
and produced D59** (idempotent attestation, unit in the match key, partitioned decompose,
the recall question refs, `delivered(ref)`, lineage-head dedup at agents). **Round 11
produced D60** (unit-aware surprise, decompose boundary rules, cross-via collapse).
**Round 12 produced D61** (the partition pinned on entity+attribute; the remainder child;
the one-candidate denial Question); its only non-cosmetic findings sat inside D60b's new
rule. **Round 13 produced D62** (per-origin polarity supersession: a source can retract;
the tie-point outcome; the routing-scope pin), its one blocking find inside D61c's
interaction with D59a. **A user review of D61/D62 produced D63** (a Source is the speaker,
never the platform; false-conflict resolution punishes no one; lifecycle phrasing pinned)
**and D64** (contested recall requires structural contradiction, not just margin; where
LLM judgment lives; how study surfaces semantic conflicts). The review loop continues
until a clean round, one round per user go. Doc-level reconciliation; the D52
build verdict stands.

**Next steps, in order:**
1. *(refactor)* The D1 file-move: move existing code into `interaction/ agents/ memory/graph/`,
   fix imports, run the test suite. No behaviour change.
2. *(build, Stage 1 per D52)* The graph memory: structured `remember` (match-or-create entity
   resolution), the spreading-activation `recall` (write the budget/fan-out algorithm),
   rank-by-`tanh`-confidence. **Static baseline first**, reward/study off.
3. *(build)* Turn on Questions/Events + the bounded study loop and *measure*.
4. *(deferred, D52)* rich-get-richer guard, per-topic competence, supersession/decompose, WAN.

Tuning numbers (nudge step sizes, decay rate) are deliberately deferred until
there's something to test.

## The idea

Argus is a voice-navigable, context-aware assistant. The end-to-end flow:

```
speech / keys  ->  recognized text  ->  intent  ->  (recall | act)  ->  reply  ->  speech / screen
```

Everything downstream of "recognized text" is text and intent, so it does not
care whether the words were typed or spoken.

## Compartments

Argus is a set of systems that talk only through contracts. Today there are three
(below); more can be added later (e.g. sensors for passive perception, actuators for
physical action) through their own contracts, without changing these. There is no
`core` (see D15).

| Compartment | One-line goal | Spec |
|---|---|---|
| **interaction** | Handle user input and output (the user channel). Pure I/O. | [interaction/design.md](interaction/design.md) |
| **agents** | Parse / route / dispatch, all model calls (user-configured connection), compose replies. The turn orchestrator. | [agents/design.md](agents/design.md) |
| **memory** | Store and recall what is known; a set of typed memory MCP servers (graph first). Holds conversational focus. | [memory/design.md](memory/design.md) · [graph model](memory/graph/memory-model.md) |

There is **no `core`**. It only ever existed as a cycle-breaker for a layering we
dropped; with systems talking directly through contracts there are no cycles to
break, so it was a compromise, not a real subsystem. Its duties redistribute:
orchestration -> agents, conversational focus -> memory, study -> memory. See D15.

## Topology: systems talk through contracts

Systems call each other directly; the *only* coupling rule is that every interaction
crosses a **contract**. Isolation comes from contracts being the sole interface,
**not** from restricting who-talks-to-whom (no layering, no "leaf"; an earlier draft
had both, dropped in D15). Which systems talk to which is simply which contracts
exist; it is not fixed, and adding a system means adding the contracts it needs, not
rewiring the rest.

```
   interaction  <->  agents  <->  memory     the request/reply path (a turn)
                     agents  <->  memory     memory's upkeep loop hands agents work
   memory  -->  interaction                  notifications / live view  [deferred]
```

- **agents** is where coordination lives: it parses the utterance, queries memory,
  composes the reply ("deciding what to call and returning the response").
- **memory** holds conversational focus too - per-session working memory (transient
  activation over the shared graph), not global state (D34).
- **memory and agents talk directly** (e.g. memory's study loop calls an agent
  to reason; agents call memory to recall/write). No middleman.

## Contracts (comms are the only coupling)

Each edge that carries traffic has exactly one contract. The contract is the
**source of truth for that boundary**: operations, data shapes, guarantees,
errors. Everything else inside a compartment is private and may change freely as
long as the contract holds.

Contracts are **transport-agnostic**. The contract describes the semantics, not the
wire, so an edge can be an in-process call, a local socket, or a network RPC by
swapping only its adapter. The **target is cross-process** (D18): the compartments
run as separate processes and exchange only serializable messages, so the choice of
transport per edge is configuration. Stage 1 may still run everything in one process
for development; see [runtime-topology.md](runtime-topology.md).

| Contract | Parties | Status |
|---|---|---|
| [interaction <-> agents](contracts/interaction-agents.md) | interaction, agents | draft |
| [agents -> graph memory (MCP)](memory/graph/mcp.md) | agents, graph memory | draft |
| [memory <-> interaction](contracts/memory-interaction.md) | memory, interaction | deferred (no consumer yet) |

Today: three systems and a contract for each pair that actually talks. This is not
fixed at three: adding a system (e.g. sensors, actuators) means adding the contracts
it needs, and the existing systems are untouched. The contract is the boundary, not
the topology. Note the agents<->memory boundary is **per memory type**: memory is a
set of typed MCP servers (D29), so the contract above is the *graph* memory's MCP
manifest, one of potentially several.

## Runtime topology

The compartment specs say *what* each owns; [runtime-topology.md](runtime-topology.md)
says *how they run*: **separate processes** (today three; location is configuration), **two
initiators / one responder** (interaction on input, memory on a clock, agents only responds),
all agent work as a **Task** with **interactive vs background** modes, a **queue**
feeding the background agent pool while **memory stays request/reply**, **reserved
capacity** for interactive, and **complexity-routed** model selection for background.
Captured in D18-D22. Diagrams (compartments, task routing, scaling) live in
[architecture.drawio](architecture.drawio).

## Decision log

Newest first. Each decision is small, dated, and states the *why* so it can be
revisited deliberately rather than drifted away from.

### D64 - Where the dumb check ends and the LLM begins (2026-06-11)
A user question pinned a real gap in the contested-recall trigger. (a) **Contested recall
= within `margin` AND structurally contradicting** (the D60a test: same
`{entity, attribute, qualifier}`, different value/unit/polarity). Qualifier-distinguished
candidates ("18 when cold" vs "13 when hot") are **disambiguation**, never a contest: the
agent asks "cold or hot?" or presents both; no Question minted. As previously written,
"top candidates within margin" alone would have minted a false contest for every
qualified pair. (b) **Where LLM judgment lives, stated explicitly**: memory's checks are
pure field comparison, no meaning anywhere. The judgment happens (1) at **intake**: the
extractor turns words into the structured claim and **normalizes units/phrasing where
unambiguous**; and (2) **post-recall**: the orchestrator reviews a flagged contest before
speaking and may close a false one immediately (a unit conversion, 18 ft-lb vs 24.4 Nm,
is the same spec: an equivalence / D63b false-conflict close). Unit-conversion false
contests are an **accepted Stage-1 cost**: Questions are cheap, one look closes them,
decay prunes them. Semantic contradictions beyond structure ("a quarter turn past snug"
vs "18 ft-lb") are **study's job**, offline. (c) **How study's finding becomes a
Question** (the mechanism that looks like agent-minting but is not): the studier
**writes the normalized claim** ("24.4 Nm" re-expressed as "18 ft-lb" on the same key);
the write collides structurally and memory's surprise detector mints the Question as a
side effect. The agent makes the conflict structural; memory does the minting; the
no-create_question invariant holds. See
[memory/graph/lifecycle.md](memory/graph/lifecycle.md),
[agents/design.md](agents/design.md).

### D63 - Source granularity; false-conflict resolution (user review of D61/D62) (2026-06-11)
User-driven corrections from walking the recent rounds together. (a) **A Source is the
specific speaker or document, never the platform** (refines D42/D54e): a particular forum
user is a source, "reddit" is not; a specific manual edition is a source, "the internet"
is not. The platform sets the born-from-type prior (forum -> low); the speaker carries
the identity. Why it matters three ways: **independence** (ten different users agreeing
is corroboration; ten posts by one user is one origin), **track record** (one
reliably-right person must not credit a whole site), and **retraction** (D62a is per
speaker: one user taking something back must not erase another's statement). (b)
**False-conflict resolution**: a contest may settle by **requalifying** its candidates
rather than picking a winner ("18" -> "18 when cold", "13" -> "13 when hot", each
superseded by its qualified version): the question closes with **no loser**, and the
competence update marks **no source wrong** (both were right about different conditions;
docking the "losing" manual would be unjust). Outcome = 1 (the presumptive answer
survived, in qualified form). The resolving evidence attests the requalified claims per
D57b (the document directly when read; a minted research-finding Source when derived).
(c) Lifecycle phrasing pinned the way it is meant to be read: a bare denial's Question
means "**the source says not-X: what is it actually**" (it keys on the attribute, so any
later value resolves it; D61c's one-candidate polarity sum is just its storage form); and
decompose is for **suspect-but-don't-know** (study suspects condition-dependence but
cannot yet assign values); when study **knows** the mapping it resolves directly by
requalification, no split. See
[memory/graph/lifecycle.md](memory/graph/lifecycle.md),
[memory/graph/memory-model.md](memory/graph/memory-model.md),
[memory/graph/mcp.md](memory/graph/mcp.md).

### D62 - Round-13 closures: per-origin polarity supersession (a source can retract) (2026-06-11)
Round 13's one blocking find sat in D61c's interaction with D59a's idempotency key; the
core model held an eighth straight round. (a) **An attestation with the same
`(source, via)` and opposite polarity supersedes the prior one**: latest polarity wins per
origin; the old edge is kept as history but excluded from the confidence sum (the D57d
read-time-exclusion idiom; amends D59a, mirrors D60c). Without this a source could never
retract: assert -> deny -> reaffirm left `c×(+1) + c×(−1) = 0` forever (D59a treated the
reaffirm as a mere refresh of the original), pinning a twice-confirmed fact at zero
confidence and putting the same Source on both sides of its own contest's frozen involved
set (simultaneously right and wrong at resolution). One origin now contributes exactly one
signed value, always its latest. (b) **The D61c outcome operand is defined at the tie**:
overturned = the prior belief's derived confidence **fails to remain positive** (sum ≤ 0
-> outcome 0), so prediction error is computable at exactly-balanced polarities. (c)
**D61a's match rule governs the partition only**: resolution routing matches **exact**
keys; an unqualified resolving claim therefore takes the D59d parent-key early close
(mooting the qualifier children), never a multi-child match. (d) Cosmetic: same-step
closure text reads "its candidate(s)" (covers the one-candidate denial); D60's header
notes D61's correction of its (e) phrasing. See
[memory/graph/lifecycle.md](memory/graph/lifecycle.md),
[memory/graph/mcp.md](memory/graph/mcp.md),
[memory/graph/memory-model.md](memory/graph/memory-model.md).

### D61 - Round-12 closures: the decompose partition pinned; the remainder child (2026-06-11)
Round 12 found both its non-cosmetic defects inside D60b's partition rule; the core model
held a seventh straight round. (a) **Partition matches on `{entity, attribute}`; qualifier
discriminates only when the candidate carries one.** An unqualified candidate matches
**all** children sharing its `{entity, attribute}` and splits its weight among them; a
qualified candidate matches only the qualifier-equal child. D60b's per-child key
`{entity, attribute, qualifier?}` under Stage-1 **exact** qualifier matching made the
qualifier-split decompose a no-op: the pre-split contest's candidates are unqualified, so
they matched no child, children were born with zero candidate edges, and the split rule
could never fire in the exact scenario it was written for. (b) **Unmatched candidates move
to an automatic remainder child** carrying the parent's own key, born like any child
(parent's uncertainty, `{none, 0}` snapshot, re-derived at first recall). Supersedes
D60b's "stays on the parent at ~1": that rule gave the remainder a discount proxied by
`max(open children)`, which tracked siblings unrelated to the remainder's contest and
vanished when they closed, leaving an unresolved contest undiscounted until a later recall
re-minted it. With the remainder child, the parent is always **pure bookkeeping** (max of
open children; close rules D58d/D60e unchanged), the remainder is a first-class open
Question, and the agent may explicitly abandon it if it is truly moot. (Also corrects
D60e's "zeroed edges" phrasing: post-D61 the parent's edges genuinely are ~0 again; every
candidate lives on a child.) (c) **The polarity-only surprise is defined**: a bare denial
of an existing claim (same content key, opposite polarity, which claim-level
match-or-create routes to the same node) mints a **one-candidate** Question: the contest
is the node's own polarity-mixed attestation sum, the snapshot is the claim's pre-denial
confidence, and outcome = 1 if the prior belief survives resolution, 0 if its derived
confidence flips negative. (d) Hygiene: markers added to D43/D44 (surprise comparison
amended by D60a), D48 (freshness derived per D51b; actions extended by D57a/D58b), D59
(its next-turn-resolves_ref claim corrected by D60d); mcp's attestation-idempotency note
gains the D60c cross-via collapse clause. See
[memory/graph/lifecycle.md](memory/graph/lifecycle.md),
[memory/graph/mcp.md](memory/graph/mcp.md).

### D60 - Round-11 closures: unit-aware surprise, decompose boundaries, cross-via collapse (2026-06-11) - (b) partition rule superseded by D61a/b (entity+attribute partition; the remainder child); (e)'s "zeroed edges" phrasing corrected by D61b
Round 11 audited D59 and found five boundary defects in its new rules; the core model held
a sixth straight round. (a) **The surprise/conflict test is the complement of the match
key**: same `{entity, attribute, qualifier}`, different `(value, unit)` or polarity. D59b
put `unit` in the *match* key but the surprise comparison still read "different value", so
a user asserting 18 Nm against a high-confidence 18 ft-lb minted a separate claim and
tripped **no** surprise (value 18 = 18): the design's own safety example, reopened on the
assert path. (b) **Decompose boundary rules**: a candidate matching **no** child stays on
the **parent at ~1** (the parent keeps discounting the unpartitioned remainder; still no
own resolution run), else a key-changing decompose silently stopped discounting the
unresolved contest; `parts` gain `qualifier?`, and children sharing a key **split** the
candidate edge weight (else a qualifier split re-multiplied the discount D59c killed).
(c) **Cross-via collapse**: a direct attestation with the same `(source, claim, polarity)`
**supersedes** the `via:"machine"` one (reading the same document validates the
extraction), never adds to it; the D59a key included `via`, so one manual could otherwise
contribute twice (`tanh(c + cap) > tanh(c)`), a one-origin double-count. (d) **Inline-ask
answers resolve via structural topic-match**: D59e's "next-turn `resolves_ref`" had no
carrier across the turn boundary (agents holds no session state; `Reply` carries no ref),
and none is needed, `remember`'s topic-match already feeds/resolves the open Question;
the claim is corrected rather than a new carrier added. (e) **Direct-parent resolution =
the D59d early close**: a resolving claim matching the parent's key (no child match)
closes the parent, open children close-as-moot, the resolving `remember`'s attestation
lands normally, and no resolution update runs through the parent's zeroed edges (the
"resolves the parent" phrasing contradicted "the parent never runs a Section-5 update").
Hygiene: `note_surfaced` removed from check-in's tools (its two call sites are agents
plumbing and the orchestrator; a push-time stamp would mark queued Prompts surfaced before
delivery); delivery plumbing stamps **Question/Event refs only** (a `kind:"result"`
Prompt's Task ref is not stamped); memory-model's freshness line updated to the derived
counter (D51b) and its attestation key un-abbreviated to `(source, claim, polarity, via)`;
D54's header gains its D58a marker; the "neither path can re-ask" claim softened to what
the carriers deliver (the stamp stops check-in re-asks; an inline ask is contextual to the
user's own utterance). See [memory/graph/lifecycle.md](memory/graph/lifecycle.md),
[memory/graph/mcp.md](memory/graph/mcp.md),
[memory/graph/memory-model.md](memory/graph/memory-model.md),
[agents/design.md](agents/design.md),
[contracts/interaction-agents.md](contracts/interaction-agents.md).

### D59 - Round-10 closures: idempotent attestation, the unit key, partitioned decompose, the missing carriers (2026-06-11) - boundary rules amended by D60 (surprise key, decompose extremes, cross-via); (e)'s next-turn-resolves_ref claim corrected by D60d (topic-match); (a)'s idempotency amended by D62a (opposite polarity supersedes per origin)
Round 10 audited the D58 patch set and found five blocking defects in the new machinery
plus two contradictions; the core model held a fifth straight round. (a) **Attestation is
idempotent**: one attestation per `(source, claim, polarity, via)`; a repeat refreshes
timestamps and nothing else. Without this, the user re-stating a fact or a manual
re-ingested added a second attestation from the same Source and `tanh(2c) > tanh(c)`:
repetition raised truth, the exact illusory-truth failure D38 forbids (D10 hinted the
rule, "same claim from a NEW source = a new attestation edge"; nothing enforced the
same-source case). (b) **`unit` joins the claim match key**:
`{entity, attribute, value, unit, qualifier}` (amends D58h). Without it 18 Nm merged into
18 ft-lb with no surprise (the value matched), silently corrupting a safety-critical spec.
(c) **Decompose partitions the parent's candidate edges by key match**: a candidate wires
at ~1 only to the child whose `{entity, attribute}` it matches, ~0 elsewhere.
Default-wiring every child to every parent edge multiplied the discount by the child count
(3-way decompose: u -> min(1, 3u)), silencing claims harder than the original contest:
D58d killed parent-vs-children double-counting but not children-vs-children. (d) **Early
parent close settled** (mcp/lifecycle disagreed): the or-sooner branch stays (a child's
resolution structurally answering the parent's key closes the parent); open siblings then
**close-as-moot** (cold, kept; a recurrence reopens via the closed-dedup path). (e)
**`recall` returns the attached/minted open-Question refs** (`questions?: id[]` on the
envelope): the inline-ask half of D58j had no operand (the gate said "ask" but the
orchestrator had no ref for `note_surfaced`, and the user's next-turn answer had no id
for `resolves_ref`). (f) **`delivered(ref)`**: a third interaction->agents operation
reporting that a queued Prompt was actually surfaced; handled by agents **plumbing**,
mechanically (no model call), which invokes `note_surfaced`. "Delivery is reported back"
had no op, and the fire-and-forget check-in Task that pushed the Prompt no longer exists
to receive anything. (g) **Lineage-head dedup moves to agents** (interaction is pure I/O
and cannot walk supersedes chains): agents resolves every pushed ref to the lineage head
and stamps `Prompt.supersedes_ref?` (the prior head), so interaction replaces queued
Prompts by simple id equality. Hygiene: the three stale tool enumerations gain
`revise_question`/`note_surfaced`; markers on D55/D56/D58; park/resume join
`revise_question`'s lead prose; "else the parent rule" defined (no matching child: the
claim resolves the parent if its key matches, else it lands as a plain `remember` with no
resolution); CONTEXT's standing-open list gains the budget item. See
[memory/graph/lifecycle.md](memory/graph/lifecycle.md),
[memory/graph/mcp.md](memory/graph/mcp.md),
[memory/graph/memory-model.md](memory/graph/memory-model.md),
[contracts/interaction-agents.md](contracts/interaction-agents.md),
[agents/design.md](agents/design.md).

### D58 - Question-lifecycle composition fixes (targeted re-trace) (2026-06-11) - match key, decompose wiring, and delivery carriers amended by D59
A targeted re-trace of just the Question lifecycle (birth -> rot -> revise -> park/resolve
-> reopen) verified the post-D57 rules compose. Verdict: the core path (mint, discount,
resolve, close) is buildable with two cross-cutting fixes; the D57 revision machinery
(reframe/decompose/park) did not yet compose. Fixes: (a) **the snapshot is a pair**
`{presumptive: claim-id | none, confidence}` (amends D54b/D57f): the outcome operand
("confirmed vs overturned") compares *identities*, and only the confidence number was
stored, so prediction error was uncomputable; gap/study-born = `{none, 0}` with outcome = 1
on any resolution. (b) **Park is reversible**: `revise_question` gains **`resume`**, and
study's consistency scan resumes a parked Question when new evidence touches its candidates
(a new attestation or Event on a candidate claim). Without this, park was a one-way door:
frozen freshness, never re-batched, dead to a world that changed. (c) **Decompose children
are born with the parent's uncertainty** and snapshot `{none, 0}`, both re-derived at first
recall (they were undefined, making the parent's max() and every inherited discount
unreadable). (d) **One contest discounts once**: on decompose the parent's candidate-edge
weights drop to ~0 (the children carry the discount); the parent keeps `uncertainty =
max(open children)` as closure bookkeeping only and **closes silently** when all children
close (no Section-5 run of its own, or competence/weights double-update through the shared
edges). (e) **Question-side supersession, mirroring D57d**: a reframed Question is
**closed-as-superseded** at reframe time: it stops discounting, is invisible to dedup, and
no longer blocks GC; only lineage **heads** count. `resolves_ref` **follows the chain to
the head** (a user's answer to a since-reframed Prompt lands on the live Question; for a
decomposed target it applies to the child whose key the claim matches); queued-Prompt dedup
compares refs at the lineage head. Without these, a reframe chain triple-counted discounts,
dedup could refresh dead Questions, and the GC guard blocked pruning forever. (f) **The
involved set is frozen at mint**: resolution step 3 updates the competence of the
candidates' attesting sources *as of mint*, excluding the resolving remember's own
attestation, so a settler never marks itself right for agreeing with itself (the
step-2/step-3 ordering self-boosted every resolver: research findings, the user, all of
them). (g) **The reopen pointer has a creator**: dedup also matches **closed** Questions on
the key; a closed hit is never refreshed, the new Question instead gains a **reopens** edge
to the cold one (D43's reopen line asserted the pointer; nothing created it). (h)
**Claim-level match-or-create stated**: a `remember` whose structured claim matches an
existing claim on `{entity, attribute, value, qualifier}` attests the existing node instead
of minting a duplicate (D57b's one-attestation rule silently required this); also noted a
surprise-minting `remember` has no `resolves_ref`, so its same-step rung comes from
`source_type` x `claim_type` alone. (i) **Attempts stamp on any dispatch carrying the
Question id** (either lane; user-requested research previously never rotted freshness). (j)
**`note_surfaced`**: a tiny op stamping a Question/Event as actually surfaced to the user,
called on reported Prompt delivery AND on an inline D30-gate ask (which previously never
stamped, so check-in could re-ask minutes after an inline ask). Ask-spacing (D57e) keys on
this stamp. See [memory/graph/lifecycle.md](memory/graph/lifecycle.md),
[memory/graph/mcp.md](memory/graph/mcp.md),
[memory/graph/memory-model.md](memory/graph/memory-model.md),
[agents/design.md](agents/design.md),
[contracts/interaction-agents.md](contracts/interaction-agents.md).

### D57 - Round-9 closures: Question-lifecycle pathologies (2026-06-11) - amended by D58 (snapshot pair; revision-machinery composition)
A ninth review hunted runtime pathologies (build-exactly-this, what breaks in week one)
instead of doc mismatches. The memory model held a fourth straight round; every finding sat
in the Question periphery. (a) **Revision lineage is capped, and Questions can be parked.**
A reframed/decomposed Question was born with zero attempts, so an unanswerable-but-important
question would rot -> reframe -> fresh counters -> research again, forever, re-arming
ask-spacing each cycle. Now: revision children **inherit the lineage's attempt count**,
counted against D47's cap (the cap now covers `revise_question` chains, not just
research-minted Questions); past the cap only park or abandon; **ask-spacing does not reset
across revisions**. **Park** (new `revise_question` action): a Question awaiting the user or
the world is exempt from study dispatch and ask-spacing pressure but stays alive, keeps
discounting its candidates, and closes normally via `resolves_ref`/topic-match; it fades
only if its importance does. Meta-review thus has a non-destructive outcome for "this
question is fine, just unanswerable right now". (b) **One attestation on Question
resolution** (mirrors D55's Event rule): the resolution's attestation IS the resolving
`remember`'s match-or-create attestation; a NEW Source is minted only when the settling
evidence is itself a new thing (an experiment, a research finding), never as a second
attestation for the same observation, and an existing settler (the user) stays ONE Source
node (D54e). As written before, one observation inflated the tanh sum twice. (c)
**Machine-extracted attestations are capped (two-hop provenance).** Bulk ingestion ("study
this manual") attributed claims to the manual at manual-grade competence, so an extractor
misread (81 vs 18 ft-lb) landed indistinguishable from the manual itself: D53c's
machine-cap protection never fired on the most common machine-write path. Now the
attestation keeps `source` = the document (identity, competence tracking) but carries
**`via: "machine"`**, and a via-machine attestation contributes at most `cap_provisional`
to the confidence sum until a validation touches it. Extraction fidelity is carried on the
attestation; document reliability on the Source. Restores the old claude-extraction cap's
protection inside the new model. (d) **Supersession is enforced at read time**: a claim
with an incoming `supersedes` edge is excluded from recall ranking (only chain heads
compete; history stays reachable on request). "Recency wins" was asserted on the write path
and enforced nowhere, so "who owns the supercharger" was a coin flip after a clean update.
Stage-1 note (narrows D52): the supersedes **edge** is written from day one (data only;
supersession-GC stays off), so routine state changes do not contest forever. (e)
**Ask-spacing keys on actual user surfacings** (amends D51b): a per-Question
last-surfaced-to-user stamp, written when a Prompt is actually delivered (the push pipeline
knows). Deriving it from the stalled-attempt counter meant failed research dispatches
widened the user-ask backoff, so escalation starved exactly when D30 says to ask the user.
Freshness (attempts) keeps gating meta-review only. (f) **The prediction snapshot is
complete**: gap-born and study-found Questions snapshot **0** (nothing was believed, so any
resolution is maximal information); a reframe inherits its parent's snapshot; a decompose
child re-snapshots at first recall; and the outcome operand is defined: **1 if the
snapshotted presumptive answer is confirmed, 0 if overturned**. Prediction error was
uncomputable for three of five birth paths. (g) **`revise_question` is structural**:
`replacement`/`parts` carry the claim-key shape `{entity, attribute, text}` and memory
wires revised Questions to the parent's candidate/about edges by default, so dedup,
topic-match, and discounting survive revision (a bare-string child was invisible to all
three). Parent/child rule: parent uncertainty = max of open children; the parent closes
when all children close (or sooner if a child's resolution structurally answers the
parent's key). (h) Formula and hygiene: `decay_eff = decay / max(importance(a),
importance(b), floor)` with `floor` an explicit dial (the unclamped form annihilated
low-importance links in one tick instead of forgetting them); **uncertainty ∈ [0,1]**
(pinned; it feeds clamp01 sums and the ε test); check-in recalls pass `nudge:false`; a
queued Prompt **replaces** an undelivered Prompt with the same `ref` (no double-asks);
`track_event`'s `about`/`resolves` get name-or-id match-or-create; the researcher gains
`search` + `recall(nudge:false)`; the Task intent comment drops quiz/sentiment (D56);
§5.3's "involved sources" = the candidates' attesting sources; and the canalization open
item now notes that the recall-time nudge also resets decay clocks (a compounding effect
Stage-1 measurement must watch). See [memory/graph/lifecycle.md](memory/graph/lifecycle.md),
[memory/graph/memory-model.md](memory/graph/memory-model.md),
[memory/graph/mcp.md](memory/graph/mcp.md), [agents/design.md](agents/design.md),
[contracts/interaction-agents.md](contracts/interaction-agents.md),
[runtime-topology.md](runtime-topology.md).

### D56 - Round-8 closures: revise_question, quiz-as-subcall + rigor, inline sentiment, the GC guard, push classified (2026-06-11) - (a) action list extended by D57a (park) and D58b (resume)
An eighth review audited the D53-D55 patches, walked the decision-log chain, and traced six
new scenarios (four clean; GC and the quizzer loop broke). The model held; every finding was
agent-side plumbing. (a) **`revise_question`**: the one agent-side Question write, usable
only by study's meta-review (D48). Actions: **reframe** (a better-posed Question supersedes,
so the user is never asked a badly-posed question), **decompose** (split into smaller
child Questions, parent/child links; resolving parts answers or dissolves the parent), and
**abandon**. This does not break D35 (memory still mints all Questions; the agent may only
rework one that study handed it, never create from scratch). **Narrows D52's decompose
deferral**: the op carries decompose from the start; how aggressively Stage-1 study uses it
is a build-order choice. (b) **Quizzing runs as sub-calls inside the studier's task** (the
extractor-inside-the-turn pattern, D55), and `remember` gains **`rigor?: "read-one" |
"cross-checked" | "quizzed"`**, valid with `resolves_ref`, supplied by the resolving agent:
this is the carrier that lets memory see the "studied: derived + cross-checked + survived
quizzing" ladder rung (D53a) and scale the uncertainty drop (lifecycle §5); self-earned
resolutions stay capped at `cap_provisional` regardless. (c) **Sentiment is invoked inline
by the orchestrator during the turn** (same sub-call pattern); its output lands through the
orchestrator's `set_importance` and the resolution fields. Quizzer and sentiment leave the
standalone dispatch map (they are sub-roles, never dispatched as Tasks). (d) **GC guard**: a
node referenced by an **open** Question or Event is never GC-eligible (pruning it would
strand candidate edges, break the discount sum, and break D53's down-nudge handle); it
becomes eligible when the referencing Question/Event closes or is pruned. (e) **`push` is
the front door's reverse direction**: it rides the interaction<->agents contract and
transport, not a separate MCP server on interaction (D27's plane rule never classified it).
Plus a marker sweep over the log (ten headers gained forward pointers; worst was D50, whose
reverted cascade read as buildable) and summary fixes in CONTEXT.md. See
[agents/design.md](agents/design.md), [memory/graph/mcp.md](memory/graph/mcp.md),
[memory/graph/lifecycle.md](memory/graph/lifecycle.md),
[memory/graph/memory-model.md](memory/graph/memory-model.md),
[contracts/mcp-pattern.md](contracts/mcp-pattern.md).

### D55 - Round-7 carriers: source type, the intent->role map, research delivery, focus-vs-importance, the nudge flag (2026-06-11) - (b) map amended by D56b/c (quizzer + sentiment became sub-roles)
A seventh review traced six end-to-end scenarios; four traced clean and every break was a
missing carrier, none touched the model. (a) **`remember` (and the Event-resolution path)
carry `source_type?`** ("user" | "manual" | "paper" | "experiment" | "web" | "forum" |
"machine"), agent-supplied, consumed only when a Source node is first created (D42's
born-from-type prior; unknown -> low prior). Memory cannot classify (it does not reason);
mirrors `claim_type` (D54a). Without it, cold-start competence, the rigor of resolving
evidence, the machine cap (D53c), and the D49 authority test all had no input. (b) **The
intent->role map is pinned**: `turn` -> orchestrator, `extract` -> extractor, `research` ->
researcher, `study` -> studier, `quiz` -> quizzer, `sentiment` -> sentiment, `check-in` ->
**check-in**, a new role (tools: `recall`, `search`, `remember`, `push`) that owns D40's
gather-due-Events-and-escalate loop. `push` finally has owners (check-in; researcher for
result delivery). (c) **User-requested research results are delivered via `push`**:
`Prompt` gains `kind: "question" | "follow-up" | "result"`; the background task stays
fire-and-forget and its final side effect is the push (live session, else queued).
Background tasks never carry `reply_to`; closes the contradiction with D20. (d) **Focus is
not a global importance anchor** (amends D36's anchor list). The "active focus" anchor
predates D34: it was coherent when focus was one global hot subgraph, and became a
cross-session collision once focus went per-session (session A opening cressida must not
shove session B's global rankings). Focus biases *relevance within its own session* only;
the global anchors remain the user, stakes, and sentiment. The legitimate intuition ("what
I work on matters") is served by weight (use wears paths), and, if measurement shows study
starving active projects, by the agent deliberately raising a `set_importance` anchor from
sustained engagement: a visible write, not a side effect of `activate`. (e) **`recall`
gains `nudge?: bool`** (default true): adversarial and self-directed recalls (quizzer,
studier sweeps) pass false, so study walking the graph does not wear paths like real use
(weight stays a record of *user-relevant* reachability). Plus the round's mechanical
patches: the Task `budget` field (D47's promised bound), dispatch-time attempt stamping
(D48's freshness can now rot), the one-attestation rule on Event resolution (no
double-count, D43b), the same-step-closure rule for surprises (Section 5 applied to the
minting claim), and the extractor running synchronously inside the turn (D44's "off the
hot path" means memory's hot path and bulk ingestion, not the turn). See
[agents/design.md](agents/design.md), [memory/graph/mcp.md](memory/graph/mcp.md),
[memory/graph/memory-model.md](memory/graph/memory-model.md),
[contracts/interaction-agents.md](contracts/interaction-agents.md),
[runtime-topology.md](runtime-topology.md).

### D54 - Round-6 carriers: claim type, snapshot semantics, remember/recall schemas, source identity (2026-06-11) - (b) snapshot amended by D58a (a pair: presumptive claim-id + confidence)
A sixth review (fresh-context) swept remaining old-design artifacts (doc/RAG leftovers in
the MCP manifest, the workspace-shaped `activate` output, pre-D38 hard-rule phrasing,
question-routing fossils) and surfaced five promised-but-uncarried mechanisms, the same
class as D53(b). Decisions: (a) **the claim carries `claim_type: "empirical" |
"derivable"`** (optional on `remember`, extractor-supplied, stored on the claim, **default
`empirical`**). The D53 ladder fork and the D49 user guard both key on this distinction,
and memory cannot classify (it does not reason), so the extractor is the only thing that
can. Empirical is the safe default: the user stays floored and only the world settles it.
(b) **The prediction snapshot is defined for recall-born Questions as the top-ranked
candidate's raw confidence at mint time** (memory's presumptive answer; it cannot know
what the agent later commits, since the gate runs after recall and D53 removed the
feedback op). And **resolution consumes the snapshot**: Question/Event resolution
magnitudes scale by prediction error (|resolved outcome - snapshot|), which was promised
(D35/D43d) but never read anywhere. (c) **`remember` loses its `status` field** (amends
D53c's `applied | conflict`). Under append-only + D43(b) a conflicting assert is *applied*
and the Question carries the conflict, so a standalone `conflict` status was a shadow of
the dropped write-gating with no defined trigger. The result is flags only:
`{ surprise?, question_minted?, question_resolved?, supersession_refused? }` (the last
reports the D51c guard case). (d) **`recall` returns an envelope**: `{ found, results:
[{ fact, confidence, effective_confidence, activation, attestations[] }] }`. Raw vs
Question-discounted confidence were ambiguous exactly where the D30 gate needs precision
(the gate reads `effective_confidence`); the old per-fact `weight` was a fused-strength
leftover (weight lives on links, D38) and becomes `activation`, the per-session
reachability the spread computed; `found` finally has a place to live. (e) **`source` is a
name-or-id with the same match-or-create semantics as `entity`** (D51e). Competence
tracking needs stable Source identity: the user must be ONE Source node across all
sessions, or their track record scatters across copies and trust can never accumulate.
See [memory/graph/memory-model.md](memory/graph/memory-model.md),
[memory/graph/lifecycle.md](memory/graph/lifecycle.md), [memory/graph/mcp.md](memory/graph/mcp.md).

### D53 - Round-5 consistency fixes: claim-type ladder, recall-time weight nudge, staging superseded (2026-06-11) - (c) statuses amended by D54c (flags only, no status field)
A fifth read-through found two contradictions and one unwired mechanism. All three resolve
from machinery already in the design; nothing new is invented. (a) **The quality ladder is
claim-type-dependent, not one total order.** The docs ordered studied vs
competent-user-confirmed both ways. The fork falls out of the existing derivable-vs-empirical
split plus D32/D49: a **real-world result is always the top**; on **empirical** claims the
**competent user outranks study** (the world or the person who owned/did the thing must
settle it; research can read about it but not settle it, which is exactly why research
disagreement cannot demote the user there, D49); on **derivable** claims **studied outranks
user opinion** (a derivation that survives adversarial quizzing is its own ground truth;
holding studied ground in teaching mode is the anti-sycophant stance, D32). (b) **The
good-use weight nudge happens at recall time; no feedback op, no retained trail.** The
promised "good answer nudges the links it used" had no carrier: activation evaporates at end
of turn (D34), the outcome arrives later, and no tool reports it. The fix falls out of D38's
own separation: weight is *relevance*, not truth. A path traversed to a returned candidate
was relevant to the request whether or not the claim was right (rightness is confidence's
channel), so the up-nudge applies **during the recall itself**, while the session's
activation is live. Down-movement is decay plus a Question resolving **against** a candidate
(its candidate edges are the structural handle). A returned-but-wrong claim keeping a small
reachability boost is correct: it must stay reachable to be corrected. Fallback if Stage-1
measurement shows this too noisy: an explicit `feedback` op carrying a `recall_id` trail
handle (documented, not built). Still open: the carrier for **sentiment-sourced magnitude**
(ridicule/emphasis scaling a resolution); decide at Stage-1 step 3. (c) **Write-staging is
superseded: protection moves from write-time gating to read-time honesty.** `remember`'s
`staged` status and the carried-over "LLM enrichment is staged, never auto-applied" rule
date from the old model, where a machine-written wrong spec was indistinguishable from a
stated fact. The new model replaces that function structurally: a machine claim's **Source
is born with capped competence** (D42, `cap_provisional`), so its **derived confidence is
capped** until real validation; provenance is first-class; and the D30 gate keeps quiet
claims from being asserted confidently. A staged-invisible claim is strictly worse than an
applied-but-quiet one (it cannot be recalled, corrected, or studied). `remember` statuses
become `applied | conflict`. **Supersedes the staged-enrichment carried-over hard rule.**
(d) **`activate` carries `session_id`** like `recall` (D51f): focus is per-session (D34) and
pooled workers share MCP connections (D21), so focus cannot be connection-bound state;
resolved to an explicit argument. (e) Fossils and notes: the stale open-questions block
pruned; memory-interaction's already-decided question-routing item removed (D40/D50);
`render` vs `push` overlap fixed (unprompted messages are `push`'s job, D40); a tuning note
that single-source confidence ceilings at `tanh(1) ≈ 0.76` so "high-confidence" thresholds
must sit below it; **importance per-anchor bookkeeping** (cooling only what depended on an
anchor implies per-anchor contribution tracking or full re-propagation) added to the open
list. See [memory/graph/memory-model.md](memory/graph/memory-model.md),
[memory/graph/lifecycle.md](memory/graph/lifecycle.md), [memory/graph/mcp.md](memory/graph/mcp.md).

### D52 - Stage-1 scope: build the static baseline, defer the soft write-path (2026-06-08) - decompose deferral narrowed by D56a (the op exists from the start); supersedes-edge write un-deferred by D57d (read-time exclusion; GC still off)
What Stage 1 builds vs defers, so the build is not blocked on soft semantics. **ON:** one
process; structured `remember`; recall = spread-by-weight then rank-by-`tanh`-confidence
(discount clamped); **one scalar competence per source** (no per-topic); structural
surprise/dedup; Questions and Events; importance + a **bounded** study loop (D47). **OFF /
simpler in Stage 1:** `mode:update` behaves as `assert` with **supersession and superseded-GC
disabled** (so F1's destruction path cannot exist yet); **decompose** (D48) deferred;
**per-topic** competence (D42/D49) deferred to one scalar; **qualifier-scoped** surprise
simplified (qualifier carried, exact-match, revisit); Event **context-triggers** deferred
(time only); all of NATS/mTLS/pool/WAN (D24). The soft parts (qualifier matching, "topic",
the spreading-activation budget/fan-out) **harden against real data**, not a fifth review.

### D51 - Round-4 corrections: undo the over-patch and close the update hole (2026-06-08) - (b) ask-spacing carrier amended by D57e (keys on actual user surfacings)
Round 3 over-patched; the fourth review caught it. (a) **Confidence stays lazily derived**
from live competence (D38/D12, free), **reverting D50(b)'s async cascade** (it solved a
non-problem and created read-your-writes staleness). (b) **Freshness (D48) is a *derived*
stalled-attempt counter** (attempts since uncertainty last dropped), not a separate stored
scalar; ask-spacing is a function of it. (c) **`mode:update` is not a silent overwrite**: an
`update` that contradicts a **high-confidence, non-user-attested** claim runs the surprise
check and mints a low-urgency Question instead of superseding; **GC of a superseded claim
preserves attestation stubs** (source, polarity, value) so provenance and competence survive.
**Amends D10** (history survives). (d) **Cold-start: confidence = `tanh(Σ competence ×
polarity)`** with competence in `[0,1]`; drop the contradictory "confidence = competence"
phrasing (D42/D9). (e) **`remember` plumbing**: `entity` is a **name-or-id** (memory
match-or-creates), add **`resolves_ref?`** so a proactive answer closes its originating
Question/Event (the D45 ref pipe ended one hop short), and the **extractor gets `search` +
`recall`** so it can resolve ids and make an informed assert/update. (f) Fossils: D36
importance propagates by **weight** (not superseded "strength"); `recall` carries a
**`session_id`** (activation is per-session, D34); Event `when:context` triggers deferred. See
[memory/graph/memory-model.md](memory/graph/memory-model.md),
[memory/graph/lifecycle.md](memory/graph/lifecycle.md), [memory/graph/mcp.md](memory/graph/mcp.md).

### D50 - Round-3 hot-path and consistency fixes (2026-06-08) - (b) reverted by D51a
(a) `remember`'s `ApplyResult` reports **`{ surprise?, question_minted?, question_resolved? }`**
so the orchestrator can act on / narrate what the call triggered. (b) The **competence
re-derivation cascade** (resolving a Question re-rates every claim a re-rated source attested)
moves **off the hot path** to a background task; only detection/dedup stays synchronous in
`remember`. (c) **Superseded claims are GC-eligible regardless of importance** (archived to a
cold store; update-chains compacted), so the graph does not grow unbounded. (d) Consistency:
D15's body is amended by D34 (focus is per-session, not the global hot subgraph); `activate`
renames `workspace`/`active_workspace` -> `focus` (a seed, not a partition, D41); the
memory-interaction `notify(kind:"question")` op is dropped in favor of D40's `push`. See
[memory/graph/lifecycle.md](memory/graph/lifecycle.md), [memory/graph/mcp.md](memory/graph/mcp.md).

### D49 - The user is a competence special case (2026-06-08)
The user's per-topic competence (D42) is **floored** and, on **empirical** claims about the
user's own domain, can be lowered **only by a real-world outcome (an Event) or a genuinely
authoritative source**, never by mere research disagreement (research-first, D30, must not
demote the user on something it cannot itself settle). This stops the assistant from
self-training into distrust of the user and growing argumentative over time. With D46's
update-vs-assert, a user *state change* is a supersession, not the user "being wrong." See
[memory/graph/memory-model.md](memory/graph/memory-model.md).

### D48 - Question freshness; rot -> meta-review (reframe / decompose / delete) (2026-06-08) - freshness made derived by D51b; actions extended by D57a (park) and D58b (resume)
Each Question carries a **freshness** value: it decays on each unresolved research attempt or
surfacing and **refreshes on genuine progress**. When freshness rots past a threshold, study
hands the question to an agent for a **meta-review** that **reframes** it (a better-posed
Question supersedes it), **decomposes** it into sub-Questions (parent/child links; resolving
parts answers or dissolves the parent), or **deletes/abandons** it. A stale important question
is thus *reworked or retired*, not nagged forever. Separately a light **ask-spacing** backoff
governs how often an unresolved question is surfaced to the user (the question stays alive;
the *user* is asked occasionally). Questions gain **reframe (supersede)** and **decompose
(parent/child)** links. Together with importance-decay (which already culls the no-longer-
relevant, the 3a point) this closes the nagging doom-loop. See
[memory/graph/memory-model.md](memory/graph/memory-model.md),
[memory/graph/lifecycle.md](memory/graph/lifecycle.md).

### D47 - Bound the study / background layer (cost + termination) (2026-06-08) - cap extended to revision chains by D57a
The study/check-in loop must not run unbounded model work on an idle machine (D25 allows a
billable connection). Every **background task carries a token/time budget**; the study loop
**idles down** when the open-Question/Event queues are empty and nothing changed (event-driven
wake + exponential backoff, not a pure clock); and Question generation from research has a
**depth/rate cap** so it cannot recurse. See [runtime-topology.md](runtime-topology.md),
[memory/graph/memory-model.md](memory/graph/memory-model.md).

### D46 - Claim shape extended; flagged as the deepest fragility (2026-06-08) - amended by D51c (update guard: no silent supersession of a high-confidence claim)
Extends D44. The structured claim gains an optional **`qualifier`/context** field (where
conditions live: "18 ft-lb *when cold*") and a **`supersedes`** link, and the agent labels
each `remember` as **`assert`** (a claim) or **`update`** (a state change). A state change
**supersedes** the prior value (append + supersede edge, recency wins) instead of
false-conflicting; surprise fires only on a genuine `assert` that disagrees with a
high-confidence claim **with a matching qualifier**. **DEEPLY NOTED:** the structured claim
is the single part of the design most likely to need rework, the triple+qualifier is a
Stage-1 simplification of real (temporal, conditional, ambient) knowledge, not a settled
model; revisit before relying on it. See [memory/graph/memory-model.md](memory/graph/memory-model.md).

### D45 - Contract and formula fixes from the second review (2026-06-08) - amended by D54b (recall-born snapshot = top-ranked candidate at mint time)
Patches that make the reward loop actually runnable: (a) **`Utterance` carries
`reply_to_ref?`** so a user's answer to a proactive `push(Prompt)` routes back to the
originating Question/Event; interaction remembers the surfaced `ref` and stamps the next
utterance, a queued follow-up re-binds on delivery. (b) **MCP resources are global**
(`memory://entity/{id}`, `memory://doc/{id}`, `memory://snapshot?focus=...`), not
`memory://{workspace}/...`, focus filters, never partitions (completes D41). (c) The
**recall discount is clamped** to `[0,1]` (or product form `Π(1 − uᵢwᵢ)`) so accumulated
Question uncertainty cannot drive confidence negative. (d) **`squash` = `tanh`** as the
placeholder bounding function (the static-baseline ranking needs it defined). (e) The
**prediction snapshot** (D43d) is the **raw derived confidence of the committed answer** at
answer time, not the self-discounted value and not Question-birth time; for a born-and-closed
**surprise**, snapshot the **prior belief's** confidence (before the contradiction) so
prediction error is not trivially zero. (f) A **clock-originated proactive push runs as its
own session**, seeded with focus from the Event/Question's `entity`/`about`; *when* to
interrupt is interaction's call (needs session identity defined enough to mean "live
session"). See [memory/graph/memory-model.md](memory/graph/memory-model.md),
[memory/graph/lifecycle.md](memory/graph/lifecycle.md),
[contracts/interaction-agents.md](contracts/interaction-agents.md).

### D44 - Structured claims at the remember/Question boundary (2026-06-08) - surprise comparison amended by D60a (complement of the match key, incl. unit)
The keystone the second review surfaced. `remember` carries a **structured claim**
`{ entity, attribute, value, unit?, polarity }` (plus optional original `text` for
display/provenance), **not an opaque string**. The agent (the **extractor** role, a model,
at intake, off the hot path) produces the triple. This lets memory do its hot-path jobs
**structurally, with no model**, honoring "memory does not reason": **surprise** = same
`entity`+`attribute`, different `value` vs a high-confidence claim; **Question dedup /
topic-match** = key on `entity`+`attribute`; **recall** `want:value` reads the `value`
field. `value` may be a scalar or an entity ref (relationships, e.g. `Cressida.engine =
2JZ`); memory resolves `entity`/`value` refs via match-or-create (which is also the
intake entity-resolution the build needs). **Why:** surprise, dedup, and topic-match were
unrunnable on free text without a model; the structured triple is the one decision that
makes the whole D35/D43 machinery work while keeping memory model-free. See
[memory/graph/memory-model.md](memory/graph/memory-model.md),
[memory/graph/mcp.md](memory/graph/mcp.md).

### D43 - Reward/Question mechanics finalized (2026-06-08) - snapshot semantics amended by D45e/D54b; surprise comparison by D60a
Closing the reward-loop details from the design review: (a) **surprise detection is
structural** in `remember`, a new claim vs a high-confidence claim about the same
entity/attribute with opposite value/polarity mints a Question; no model on the hot path.
Deeper **semantic** conflict-finding is a **study-agent** job, later. (b) **A conflict is
represented by a Question only**, competing values stay separate claim nodes with their own
positive support; we never add cross-negative "X disproves Y" attestations, so there is no
double-count between derived confidence and the recall discount. (c) **Questions dedup**:
search for an existing open Question matching the contest (topic + candidates) before
minting; refresh it instead of duplicating. (d) **Snapshot the answered confidence** onto
the Question/Event at mint/answer time, so reward **prediction error** (answer-time
confidence vs the resolved outcome) is computable (confidence is otherwise derived and not
stored; a Question/Event is not an immutable Fact, so it may carry a stored scalar). See
[memory/graph/memory-model.md](memory/graph/memory-model.md) and
[memory/graph/lifecycle.md](memory/graph/lifecycle.md).

### D42 - Competence by source-type prior (cold-start) + self-tune; independence (2026-06-08) - cold-start formula amended by D51d (tanh)
A Source's competence is **born from its type** (factory manual / spec / peer-reviewed paper
~high; experiment / own measurement ~high by rigor; the user ~medium-high and topic-dependent
per D32; forum / random web ~low; unknown low), then **self-tunes from track record** (being
right/wrong on resolved Questions/Events). This is also **cold-start confidence**: a single-
source claim's confidence = its source's competence (the 95% path for a single user). The
**independence** qualifier in the confidence sum is handled by the type-priors (low-trust
echoes contribute little) plus the **research agent's judgment** (it counts copies of one
claim as one source); a structural **source-lineage edge is punted** to later, used only if
echo-laundering actually appears. **Concretizes D11.** See
[memory/graph/memory-model.md](memory/graph/memory-model.md).

### D41 - One global graph; drop workspace isolation (2026-06-08)
**Drops the carried-over "each project is its own graph / every query scoped by workspace"
hard rule.** It no longer fits the self-tuning model: source competence is shared across
projects (the same manual), concepts and importance propagate globally, and study walks the
whole graph. **Workspace becomes a focus / importance seed**: `activate` sets "what project
I'm in" (biasing importance and relevance), but recall, competence, study, and propagation
all operate on **one global graph**. Supersedes the workspace-isolation hard rule and the
"MCP session is workspace-scoped, no call crosses workspaces" clause in the manifest. See
[memory/graph/memory-model.md](memory/graph/memory-model.md).

### D40 - Proactive user contact: a study check-in loop + an outbound push (2026-06-08)
The reward loop needs Argus to reach the user **unprompted** (proactive Questions, Event
follow-ups), which had no delivery path. memory's **study clock** periodically gathers due
**Events** + top open **Questions** and hands them to an agent (a background task); that
agent resolves what it can with its tools (research) and **escalates the rest to the user**.
The last hop needs an **outbound push** on the interaction<->agents contract (today only
`submit -> Reply`), an agent can originate a message. **Targeting:** deliver to a **live
session** if one exists, else **queue for the next interaction**; truly urgent items push to
a default device. Memory stays the initiator (the study clock); the new capability is
agents -> interaction outbound. **Amends D19** (memory, via an agent, can originate user
contact). See [runtime-topology.md](runtime-topology.md) and
[contracts/interaction-agents.md](contracts/interaction-agents.md).

### D39 - Event nodes: pending real-world outcomes to follow up on (2026-06-08)
A **Event** node is the agent's memory of something happening in the world with a future
outcome it should check back on (an experiment "torqued to 18, will it hold?", a delivery,
a job in progress, a scheduled test). It is **created by the agent** at intake (it parses a
pending-outcome statement, unlike Questions which memory mints), carries what-to-check + a
**follow-up trigger** (time and/or context) + links to the Question(s) it would resolve, and
re-surfaces until answered. **Closing it mints a Source for a real-world result** (top of
the reward ladder), resolves the linked Question, and delivers strong reward. **Why:** the
highest-quality reward (real-world results) only exists if the system *follows up*; without
Events it evaporates because nobody checked back. Events are the sibling of Questions
(internal-uncertainty vs external-pending-outcome; memory-minted vs agent-created;
resolved-by-seeking vs resolved-by-following-up). New op `track_event`; the study clock
fires due follow-ups. See [memory/graph/memory-model.md](memory/graph/memory-model.md) and
[memory/graph/lifecycle.md](memory/graph/lifecycle.md).

### D38 - Un-fuse: weight (reachability) + derived confidence + competence (2026-06-08)
**Supersedes D31** (the single fused "connection strength"). The fusion failed one critical
case: if *use* strengthens the fused number, asking a lot raises confidence (popularity ->
truth, the illusory-truth effect), the exact failure to avoid on safety-critical specs. So
they split back into three: **weight** (stored, on association links, reachability,
use-driven, drives spreading), **confidence** (*derived* per claim,
`squash(Σ independent competence × polarity)`, never stored, so use cannot move it), and
**competence** (stored, on sources, trust/track-record, validation-driven). This keeps
relevance-learning-from-use AND honest confidence (one number cannot do both), and restores
free retroactive correction (fix a source -> every claim it attested re-rates). Reward has
two channels: good-use -> weight, validation -> mint-source + competence -> re-derived
confidence. Recall is two-stage: spread by weight (find), rank by confidence (pick).
**Restores D9/D12; supersedes D31; resolves the link-vs-node and use-strengthens tensions.**
See [memory/graph/memory-model.md](memory/graph/memory-model.md) and
[memory/graph/lifecycle.md](memory/graph/lifecycle.md).

### D37 - agents is a role registry; dispatch by intent and complexity (2026-06-08)
The agents compartment is not one prompt: it is a set of **roles**, each a
`(system prompt + tool set + output schema + model tier)` over the **one** shared model
wrapper (so the connection / never-surprise-billing chokepoint stays single, D25).
Dispatch is mechanical: a Task's **intent** picks the role (orchestrator, extractor,
researcher, studier, quizzer, sentiment, ...), its **complexity** picks the model tier
(D22). Each role does only its narrow job under its own prompt, which keeps each role's
decision-list small. Relatedly, **Questions are memory-minted, not agent-called**: the
agent's write-side decisions are just route-intent / extract / gate (D30), and `remember`
doubles as store-and-resolve (the intake surprise detector lives inside it, not in the
agent). **Why:** gives the agents compartment its internal structure and lets one
configured connection serve many specialized jobs by swapping prompt + tools, not code.
See [agents/design.md](agents/design.md).

### D36 - Importance: a distinct anchored attention value (2026-06-08) - anchor list amended by D55d (focus is not a global anchor)
**Importance** (how much a thing matters) is a node value separate from **strength** (how
true/reachable it is): selling the Cressida drops its importance (attention) without
changing its facts' strength (truth). Importance is **anchored + propagated**, a few nodes
are anchors (set by the user, a painful-error/stakes, active focus, or a **sentiment agent**
reading tone), and importance flows out across associations scaled by weight (D51 fossil
fix, not the superseded "strength"). Context
events re-anchor immediately ("this is critical" raises an anchor; "I sold the X / forget X"
archives one), and re-propagation cools only what *depended* on that anchor, shared
knowledge held by other anchors survives. Importance drives **study priority**
(`uncertainty x importance`) and **decay rate** (important decays slower: the graph forgets
the irrelevant, keeps the safety-critical); it is not a one-way ratchet. The agent maps
relevance statements to an **importance directive** on memory, separate from `remember`.
**Why:** attention and truth are different axes, and anchoring makes mass re-prioritization
(sell a car, flag a critical spec) cheap and structural. See
[memory/graph/memory-model.md](memory/graph/memory-model.md) and
[memory/graph/lifecycle.md](memory/graph/lifecycle.md).

### D35 - Uncertainty and reward live in the graph as Question nodes (2026-06-08)
Eligibility, curiosity, proactive questions, and resolution-provenance are unified into one
node type, the **Question**: a salient, active uncertainty crystallized from a contested
recall (or a surprise, or a study-found gap). It connects to its **candidate** claims
(edge weight ~1), their **sources** (~0.2), and **topic** seeds (~0), carries an
**uncertainty** scalar, and inherits **importance**. At recall a claim's strength is
**discounted** by its attached Questions' `uncertainty x edge-weight` (contested facts come
back quiet, which trips research/ask, D30). **Reward = resolving a Question structurally**:
evidence lowers uncertainty, shifts candidate strengths, **mints a Source node** for
whatever settled it (the graph grows its own evidence), and updates source competence, all
scaled by edge weight. Magnitude is **prediction error** (a confident belief overturned
flips hard). Salience is **emergent**, cheap to create, decay prunes one-offs, recurrence +
importance keep the rest warm, so no creation threshold is tuned. **Why:** puts the whole
reward/learning loop inside the inspectable graph, with clean structural credit assignment
instead of a side-band trace. **Builds on D16/D30.** See
[memory/graph/memory-model.md](memory/graph/memory-model.md) and
[memory/graph/lifecycle.md](memory/graph/lifecycle.md).

### D34 - Focus is per-session working memory, not global graph state (2026-06-08)
Conversational focus ("my current engine") is **per-session working memory**: transient
activation over the shared graph, keyed by a session id and passed as a parameter, never
a single global hot-subgraph stored on the graph. This is what lets many sessions and
pooled agent workers recall concurrently without colliding ("not locked to one instance
at a time"). The persistent graph (facts, connection strength) stays global and shared;
only *attention* is per-session. Devices and sessions are many-to-many (one conversation
can span mic + screen; one device can host different sessions over time), with interaction
assigning session identity. **Revises D15** (focus is per-session activation, not the
global hot subgraph). See [memory/graph/memory-model.md](memory/graph/memory-model.md).

### D33 - Rename "dreaming" to "study"; curiosity-driven self-learning (2026-06-08)
memory's clock-initiated loop is renamed **dreaming -> study**, because it is deliberate,
goal-directed self-improvement, not passive consolidation. Study pursues the steepest
**reward gradient** (curiosity: weak-but-important links, contradictions, gaps),
**researches and self-tests** (constructs proofs, cross-checks independent sources, and
gets other agents to quiz/refute an idea before it hardens), updates strength
**provisionally**, and banks what it cannot resolve as **questions for the user** that
harvest ground-truth reward to confirm or prune it. Two research lanes with **strict
priority**: **user-requested research** (drained first) over **self-directed study**
(slack only, small/preemptible), so curiosity is never intrusive. Decay and pruning ride
along as housekeeping. Renames the loop (was "dreaming" in D6/D15/D19) and adds the study
mechanics. See [memory/graph/memory-model.md](memory/graph/memory-model.md) and
[runtime-topology.md](runtime-topology.md).

### D32 - The user is a topic-dependent source, not ground truth (not a sycophant) (2026-06-08)
User confirmation is **not** a flat strongest signal. The user is a high-but-topic-
dependent source: near-authoritative on what they own and did, weak on what they are
asking to learn. Their input is weighted by **inferred per-topic competence** (learned
from track record, expressed certainty, telling-vs-asking), and Argus **questions the
user** when their input conflicts with well-studied knowledge (research-first, D30,
applies to user input too). In teaching mode (the user asking to learn) Argus holds its
studied knowledge rather than downgrading to match a tentative statement. **Real-world
results outrank user opinion.** The reward weighting maximizes *being right*, not *being
agreed with*. **Refines D11/D17:** the user is high but not absolute, and trust becomes
per-topic competence. See [memory/graph/memory-model.md](memory/graph/memory-model.md).

### D31 - One reward-driven connection strength (2026-06-08) — SUPERSEDED by D38
Collapses the three separate signals (weight, confidence, trust as distinct numbers,
D9/D12) and the separate link-strength-vs-confidence of D16 into **one connection
strength per link.** Strength fuses reachability/relevance and confidence, and moves on a
**reward signal** ("fire together, wire together," where the firing that wires is a
*rewarded outcome*): links behind a good result strengthen, behind a bad one decay, and
time decays all. Reward sources by quality: real-world result > studied
(derived/cross-checked/quizzed) > competent-user-confirmed > read-one-source >
mere-acceptance; correction and ridicule punish; re-asking is neutral. **The reward
weighting is the experiment.** Structure still does identity/disambiguation (distinct
entities + inheritance) and knowledge stays append-only (D10); strength is the decaying
overlay. **Keeps** D8's Hebbian-symbolic, inspectable stance (strength is a visible
number, not a hidden embedding). **Supersedes D9 and D12, and the link/confidence split
in D16.** See [memory/graph/memory-model.md](memory/graph/memory-model.md).

### D30 - Resolve uncertainty by research first, ask the user last (2026-06-08)
On uncertainty or a conflict between comparable-trust sources, Argus does **not** divert
to the user first. It **spawns an agent to research** the answer (web, docs, tools),
looking for an authoritative source or **enough independent agreeing sources**. What it
finds is written back as attestations; confidence recomputes from the new sources and
the conflict usually resolves with no user involvement. **Asking the user is the last
resort**, used only when research genuinely cannot settle it (the user is the
highest-weight settler, D17). Research is a queued task (the memory->agents queue plane)
or a bounded inline call during a live turn. **Latency is acceptable as long as the
agent tells the user what it is doing** ("let me look that up", "two sources disagree,
checking"), narrated as status messages over the interaction contract: thinking and
researching is expected, silence is not. **Independence guard:** agreeing sources count
only if they are **independent**; ten posts copying one origin are one source, not ten,
so this never launders a single bad source into confidence (consistent with "never move
trust from the graph's own confidence", D12/D17). **Why:** asking the user for
everything is unusable and wastes the one scarce settler; autonomous evidence-gathering
is what a person does, and it keeps low initial confidence from becoming constant
pestering. **Amends D17 (ordering: research primary, user last).**

### D29 - Memory is a set of typed MCP servers, not one contract (2026-06-08)
There is no single "memory contract." **Each memory type is its own MCP server with its
own tools, as a subdirectory under `memory/`** (`memory/graph/`, and later
`memory/sql/`, `memory/rag/`, ...). Hot-swap = configure the agent to a different memory
MCP. The graph-specific tools (`recall` via spreading activation, `neighbors`) are the
*graph* memory's MCP, not a leak in a universal abstraction; a SQL or RAG memory would
expose different tools. This resolves the apparent contradiction between "memory is
swappable" (the role) and a graph-specific manifest: swappability is at the MCP-server
level, not a shared interface. `memory/` keeps the role-level `system_goal.txt` and a
short `design.md`; each type folder holds its own design and MCP manifest. **Why:** the
project is researching whether the graph memory is even viable, so memory types must be
independently swappable to compare them, which a single universal contract would
prevent. **Corrects the earlier single agents<->memory contract.**

### D28 - Recall is the agent's own tool loop, not a separate translator (2026-06-08)
Clarifies what D27 "collapses." There is **no separate "specialized model" that
translates a question into a `QuerySpec`** (drops that from D14). With memory's
operations exposed as MCP tools (D27), the **agent model emits the `recall` / `remember`
tool calls directly** through native function-calling: a tool's `inputSchema` *is* the
`QuerySpec`/`Assertion`, and the model fills it. Reference resolution ("my engine",
"those cam caps") happens in the **tool loop**, the agent calls `search` to turn names
into node ids, reads focus/context, then calls `recall` with resolved ids. What MCP
removes is the **format/translation** step the model is trained for; it does **not**
remove the **reasoning** (choosing the right tool and the right arguments). That
reasoning quality is exactly what this project is built to test, not a component to
design. **Why:** function-calling already does NL->structured-call; a dedicated
translator model is a part we do not need, and overstating the "collapse" hid that the
argument-choice is the real (and testable) work. **Amends D14; refines D27.**

### D27 - Agent -> system request/response edges use MCP (2026-06-08)
Where the agent (an LLM) calls another system and waits for a result, the contract
follows the **MCP** tool/resource shape: tools = operations with JSON-Schema inputs,
resources = addressable read-only data; **agents is the host**, each called system is
an **MCP server**. The model is already trained on tool-use, so it calls these
natively, and a tool's `inputSchema` **is** the query IR, collapsing the
utterance -> concrete-question -> `QuerySpec` -> execute pipeline into a single native
tool call (**amends D14**). **Scope is precise:** MCP applies only where the LLM is the
caller **and** the call is request/response. It does **not** apply to the front door
(interaction -> agents; caller is not the LLM), to async jobs (background tasks and
memory -> agent reason/study requests, which go on the queue), or to continuous no-LLM
data (sensor ingestion / live feeds, which use a stream/write path). For a sensors
system the line is query-vs-stream: an on-demand query tool is MCP, the ingestion
firehose is not. **Constrains D25:** the agent's model connection must be
**tool-capable**. Three planes fall out: MCP (sync, LLM-caller), queue (async jobs),
stream (continuous no-LLM data), plus the front door. Rationale and full plane-map in
[contracts/mcp-pattern.md](contracts/mcp-pattern.md).
**Why:** adopts the standard LLM->system contract the model already speaks, scoped to
the one plane where it pays off, instead of forcing every edge through tools.

### D26 - Rename HID to interaction; it is the user channel; systems are open-ended (2026-06-08)
The input/output system is renamed **HID -> interaction**. It is specifically the
**user** channel (deliberate two-way communication: input in, replies out), not a
general world interface. Passive perception (cameras watching, environmental data) is
a separate future **sensors** system, and physical action (motors, relays) a separate
future **actuators** system; the split is by role, not by device (a camera a user
shows something to is interaction; a camera passively watching is sensors). This also
drops the "exactly three compartments / all-to-all mesh" framing: the system count is
**open-ended**, and new systems plug in by adding their own contracts without rewiring
the existing ones. Speech-to-text lives inside interaction (it hands agents clean
text; agents never sees raw audio). **Why:** "HID" and "turn the world into
utterances" wrongly bundled user interaction with world perception and action, and the
contract-only coupling already supports adding systems, so nothing should be fixed at
three. **Amends D1 (HID->interaction), D4/D15 (open-ended count, not exactly three).**

### D25 - Model connection is a user-configured, swappable adapter (2026-06-08)
Drops the never-bill / subscription-only hard rule (amends D5; removes the matching
carried-over hard rule). agents still brokers every model call through **one
chokepoint**, but behind it is an **opaque, user-configured connection that can reach
an LLM**: a local model, a separate inference server, a hosted API, a
subscription-backed CLI, or anything else, selected by configuration like any other
adapter. agents does not care which; it just has a configured way to call a model.
Cost, if any, is whatever that connection implies (a local model costs nothing; a
billable one only spends because the user wired it up), so protection against surprise
cost is **configuration, not prohibition**: nothing is billable unless the user
configured a billable connection. The old key-stripping in `enrich/llm.py` was
enforcement of the dropped rule and is legacy until the agents refactor replaces it.
**Why:** an LLM call is just a configured stream; pinning it to one provider (or to
billing rules) bakes into the architecture a choice that belongs in config. **Amends
D5; removes the never-bill carried-over hard rule.**

### D24 - Runtime defaults resolved: NATS broker, mTLS, strict reservation, complexity rubric (2026-06-08)
Closes the runtime-topology open points. Background broker is **NATS (JetStream)**
behind a swappable adapter (one piece of infra for both the work-queue and the later
memory->interaction notification pub/sub). Every **network** edge uses **mTLS** with
per-service identities; loopback / in-process edges are exempt; the broker and memory
authority require authenticated clients; certs/keys in `.env`, never committed.
Interactive capacity is **strictly reserved (no work-stealing)**; background tasks are
chunked so stealing could be a later opt-in. The `complexity` scale (D22) is anchored
by a fixed rubric (`0-2` trivial, `3-4` simple, `5-6` moderate, `7-9` hard), bands
defaulting to `0-4` small / `5-9` big, settings-overridable. **Why:** turns the last
operational unknowns into defaults so building can start, all swappable behind
adapters/settings. See [runtime-topology.md](runtime-topology.md).

### D23 - Placement is symmetric; resilience is a placement choice (2026-06-08)
Strengthens D18: **any compartment may run on a separate machine or on the same
machine as another, purely by configuration.** No compartment may assume it is
co-located with another, and none may assume it is remote. Consequence: there is **no
built-in replica or cache**; surviving a network partition is achieved by *placement*
(co-locate memory with the interactive node if local recall must outlast an
uplink outage), not a special mechanism. The contracts and Task envelope are identical
for every placement (all on one box, or spread across local / datacenter / storage).
**Why:** keeps deployment fully configurable without baking a topology into the code.
See [runtime-topology.md](runtime-topology.md).

### D22 - Background tasks route by complexity to a model; never name a model (2026-06-08)
A **background** task carries a `complexity` flag (`0..9`); a **complexity router**
maps it to the right model (small/cheap for trivial work, big for hard), so the big
model isn't burned on trivial work. The task declares **complexity, never a specific
model** (complexity is intrinsic and stable; the model lineup is not, so pinning a
model re-breaks every producer when models change). The complexity->model mapping is
a **configurable policy** (first cut: `0-4` small, `5-9` big; later, tested band
boundaries and per-deployment settings overrides). **Interactive** tasks skip the
router (their guarantee is availability, not right-sizing). Every task carries a
unique `id` for **correlation** (interactive) and **idempotency** (append-only
memory must not double-write on a queue retry). **Why:** right-sizes spend/latency
where nobody is waiting, and keeps model choice a swappable policy, not producer
knowledge. See [runtime-topology.md](runtime-topology.md).

### D21 - The queue feeds the agent pool; memory stays request/reply; interactive reserves capacity (2026-06-08)
The **queue is the ingress to the (background) agent pool**: producers drop tasks,
agent workers pull them, which decouples *what work* from *which worker, where* and
lets agents be a pool spread across machines (add a datacenter worker = subscribe a
process; interaction/memory unchanged). **memory is not queue-fed**: it is a **request/reply
authority** like the DB it fronts (one authority, nothing to distribute). Asymmetry
on purpose: *memory = request/reply authority, agents = background queue-fed pool*.
**Interactive gets a reserved set of resources** reached by **direct** request/reply
(not the broker), so background load can never starve a waiting human, and (kept
**local**) the interaction path survives an uplink outage while background queues up.
**Why:** isolates the latency-critical path, and scales the pool without touching the
producers. See [runtime-topology.md](runtime-topology.md).

### D20 - All agent work is a Task; two modes by interaction pattern (2026-06-08)
Every piece of agent work (from interaction or from memory's study) is one envelope
`Task { id, mode, reply_to?, complexity, intent, context, schema? }`. The two
**modes** are named for the **interaction pattern**, not the producer or purpose
(purpose like "turn"/"study" is exactly what's allowed to change): **interactive** =
a producer is waiting, carries a `reply_to`, higher priority; **background** =
fire-and-forget, results land as side effects (a write into memory). A new producer
or a different memory just emits `interactive`/`background`; agents needn't know what
it is. **Why:** one stable contract for "give agents work" that survives the
compartments evolving. See [runtime-topology.md](runtime-topology.md).

### D19 - Two initiators, one responder (2026-06-08) - amended by D40 (an agent may originate proactive user contact)
Only two things start activity: **interaction** (on input, the interaction loop) and
**memory** (on a clock, the study loop). **agents** has **no loop of its own**; it
only responds when handed a task by either initiator. interaction hands work to **agents
only** (never memory in the interaction path), or turn logic would leak into interaction.
Mental model: agents is the executive, memory is long-term memory plus the study
subconscious, interaction is the senses and mouth. **Why:** pins down "where the loop runs"
and "where Argus exists" without a `core`. See [runtime-topology.md](runtime-topology.md).

### D18 - Compartments run as fully separate processes; location is configuration (2026-06-08)
The three compartments are **independently deployable processes** that never import
each other and exchange only serializable messages defined by a contract. Where each
runs (local box, datacenter slot, rented storage server) is **configuration**, not
architecture; a contract is transport-agnostic, so in-process call vs local socket vs
network RPC is an adapter swap. **Why:** makes "rent a datacenter slot for some
agents, keep others local, rent storage for memory" a config change, and the physical
process boundary removes the import-cycle worry the mesh otherwise raised. **Amends
D3's "today every edge is an in-process call": cross-process is now the target, same
contracts.** See [runtime-topology.md](runtime-topology.md).

### D17 - Trust updates: move a source's number only on real-world results (2026-06-08) — amended by D30; the (-1..+1) range superseded by D51d (competence in [0,1])
A source's trust (-1..+1) moves **only when Argus actually finds out** who was right
- you correct/confirm, you settle a disagreement Argus asks about, or an authority
  contradicts/confirms - **never** from the graph's own confidence (no echo
chamber). Soft tone/sentiment hints are allowed but nudge the least. **Re-asking is
NOT a bad signal** (you may have forgotten); on uncertainty or conflict Argus
**asks or searches** instead of guessing. Same nudge math as link strength (small
steps toward +1/-1), **weighted by who settled it** (you > manual > web page >
tone). Moving one source's number re-rates every fact it vouched for (D12). New
sources get an agent-**guessed** starting trust (manual high, forum low), then
self-tune. **Why:** keeps trust honest (real results only), avoids punishing
forgetfulness, and prefers asking/searching over guessing.
See [memory/graph/memory-model.md](memory/graph/memory-model.md).

### D16 - Credit assignment: nudge the links a good answer used (2026-06-08) — link/confidence unified by D31; nudge trigger and down-path superseded by D53b (recall-time nudge; down = decay + Question resolution); the gradient-along-the-trail idea is unowned/open
Every link has a **strength** 0..1. A **good** answer nudges the links it used
**up** (move part-way to 1, e.g. a 20% step - big when weak, small when strong, so
it never overshoots); a **bad** answer nudges them **down** (toward 0; ~0 gets
pruned). Along the trail, the link **next to the answer** gets the full nudge and
each step back gets **half** as much. Disambiguation counts too: nudge the picked
trail up, the ignored ones down. "Good/bad" for now = used-without-complaint vs
corrected (the real reward signal is the trust topic). This only changes how easy
an answer is to **find**, never whether it's **true**. Creating new links and
pruning dead ones is **study's** job; live recall only strengthens existing
links. **Why:** simple, bounded, explainable reinforcement that builds well-worn
paths without runaway or hairball. See [memory/graph/memory-model.md](memory/graph/memory-model.md).

### D15 - Fold `core` away: three compartments, all-to-all mesh (2026-06-08) — amended by D26, D34
There is no `core`. The subsystems are **agents**, **memory**, **interaction**, fully
meshed: any may call any other, the only rule being that every interaction goes
through a contract. `core` only existed as a cycle-breaker for the (now dropped)
layering; a mesh has no cycles to break, so it was a compromise, not a real
subsystem. Its contents redistribute: **session/focus -> memory** (focus is
**per-session working memory**, transient activation, *amended by D34*, not the global
hot subgraph this entry originally said),
**intent classification -> agents** (it's a parse), **the study loop -> memory**
(calling agents directly), **turn orchestration -> agents** (parse -> query memory
-> compose reply). Contracts become the three pairs: interaction<->agents, agents<->memory,
memory<->interaction. **Why:** matches the original three-directory instinct; a mesh makes
who-talks-to-whom a non-constraint, so the contract is the only real boundary.
**Supersedes D2, D6, D7; amends D1, D4.**

### D14 - Querying: NL <-> graph via a specialized model, three-step pipeline (2026-06-07) — amended by D28
Recall is a pipeline: utterance -> **concrete question** (resolved against session
context) -> **structured query** (a specialized model translates to a `QuerySpec`
over the primitives: which facts/associations, which source/attestation, which
polarity) -> **graph executes** (spreading activation + attestation/polarity filter
+ confidence-first ranking). The same model runs the other direction for **intake**:
a heard statement -> facts + associations + an attestation with inferred polarity
(`Assertion` IR). The specialized model is an **agent**: agents parse and drive the
turn, calling memory to execute; memory's study calls agents directly too (mesh,
D15). **Why:** a clean text-to-query seam
specialized to facts/sources/polarity, and the "what engine does *the user* think
is in a Cressida" query needs the association x attestation intersection the IR
makes explicit. See [memory/graph/memory-model.md](memory/graph/memory-model.md).

### D13 - One node type (Fact), two edge types (association + attestation) (2026-06-07) — amended by D35/D38/D39
**Amended by D38:** a Fact no longer *stores* `confidence`; confidence is **derived** from
attestations × source competence. `weight` lives on association links; `trust` is renamed
**competence** and lives on a source. **Amended by D35/D39:** there are now also **Question**
and **Event** node types alongside Fact. The original entry below predates these.
There is a single node type, **Fact**, always carrying `confidence` + `weight`,
and additionally `trust` **when it acts as a source** (makes claims). "Source" is a
**role a Fact takes on**, not a separate node - a thing exists (fact) and asserts
(source) as one node (an experiment, a manual, the user). Two edge types are both
required: **association** (fact-fact, weighted) = *aboutness*, and **attestation**
(source-fact -> claim, polarity) = *provenance*. **Why:** the dual role is the
common case (every experiment/manual/person is both), so a separate `Source` node
just duplicates; and a query like "what engine does *the user* think is in a
Cressida" needs the intersection of association (about engine/toyota/cressida) and
attestation (said by the user), which one merged edge type can't express.
Supersedes the v1 "two node types" lean.
See [memory/graph/memory-model.md](memory/graph/memory-model.md).

### D12 - Signed confidence/trust; confidence is derived; weight stays separate (2026-06-07) — SUPERSEDED by D31; RESTORED by D38 (active; competence range later [0,1], D51d)
`confidence` and `trust` are signed `[-1, +1]` (-1 = sure-it's-false / reliably-
wrong). A claim's confidence is **derived**, not stored:
`squash(sum of trust(source) x polarity)` over its attestation edges, using each
source's **live** trust - so correcting a source's trust retroactively corrects
every claim it touched (lazy: free; eager: a one-hop recompute over its `ATTESTS`
edges). Trust moves only from **ground truth** (user/search/results), never from
the graph's own confidence, with a small learning rate. `weight` and `confidence`
stay **separate metrics** (not merged): they can point opposite ways (a known
falsehood = high weight, confidence -1), they have different storage models
(derived vs nudged scalar), and pruning needs both (GC only when cold *and*
uncertain). **Why:** answers the "what moves confidence / how does a trust change
propagate" question mechanistically, and keeps known-false-but-common knowledge
expressible. See [memory/graph/memory-model.md](memory/graph/memory-model.md).

### D11 - Trust is bootstrapped from a priori roots, then self-tunes (2026-06-07)
Trust anchors on a few roots: the **user** (very high, *not absolute* - a strong
manual can prompt Argus to double-check the user), designated references (high),
and new sources get an agent-**inferred** initial trust. Trust then moves on
sentiment + results (track record). **Why:** trust has to anchor somewhere or the
graph floats; even the user misremembers, and catching that is a feature.
See [memory/graph/memory-model.md](memory/graph/memory-model.md).

### D10 - Knowledge is immutable: build, never edit or delete (2026-06-07) - amended by D51c (GC keeps attestation stubs; no silent overwrite)
Claim nodes are created, never updated or deleted. Disagreement creates a **new**
node; the old goes cold but is kept as history. The only deletion is **pruning a
node whose `weight` has decayed to 0** (garbage collection). Same claim from a new
source = a new **attestation** edge, not a duplicate node; confidence is therefore
*emergent* from attestations, never an overwritten number.
**Why:** history must survive (old specs and why they changed matter), and
append-only removes the whole class of "we edited the wrong thing" bugs.

### D9 - Memory self-tunes on three independent signals (2026-06-07) — SUPERSEDED by D31; RESTORED by D38 (active doctrine)
`weight` (reachability) moves on **usage**; `confidence` (correctness, literal)
is computed from the **trust** of a claim's attestations; `trust` moves on a
source's **track record**. Reinforcement from usage touches `weight` only and can
never make a wrong fact more true. **Why:** popularity is reachability, not
correctness - critical for safety-critical specs (a wrong torque number must not
gain authority by being asked often).

### D8 - The memory model is Hebbian-symbolic, not a neural graph DB (2026-06-07) — three-signal split superseded by D31; Hebbian-symbolic stance kept
The graph stays symbolic and inspectable; "learning" is edge plasticity (fire
together, wire together) + spreading-activation recall + decay, not hidden
embeddings. **Why:** explainability is non-negotiable; a GNN/embedding store would
make recall a black box, which the project rules forbid.

### D7 - Agents never touch memory; core mediates (2026-06-07) — SUPERSEDED by D15
~~Agents do not read or write the graph; the study loop in `core` mediates.~~
Dropped with the mesh: agents and memory interact directly. The write *policy*
(capped, conflict-checked; the staged part was later superseded by D53) still lives in
memory; what changed is that agents may call it without a `core` middleman.

### D6 - The study/thinking loop lives in core, not memory (2026-06-07) — SUPERSEDED by D15
~~Study lives in `core` so memory stays a leaf.~~ With no leaf constraint,
study lives in **memory** (where it was originally placed) and calls agents
directly for reasoning.

### D5 - The model wrapper lives in agents (2026-06-07) — amended by D25
All model calls go through one wrapper in `agents`. **Amended by D25:** the original
rule was subscription-only / never-bill (strip `ANTHROPIC_API_KEY` /
`ANTHROPIC_AUTH_TOKEN`); the connection is now a **user-configured** adapter (a local
model, an inference server, a hosted API, a subscription-backed CLI, ...), but the
single-chokepoint design stands.
**Why:** one place to configure the model connection and audit cost, instead of
scattered call sites.

### D4 - One contract per pair (2026-06-07) — amended by D15, D26
Originally "one contract per *real edge* (3, given layering)". With the mesh (D15)
it's **one contract per pair**, which for three compartments is still 3:
interaction<->agents, agents<->memory, memory<->interaction. Every pair is a real edge now.

### D3 - Contracts are the source of truth for comms; transport-agnostic (2026-06-07)
Each boundary is defined by a contract (operations, data shapes, guarantees,
errors), independent of the transport. **Why:** lets a boundary move from
in-process call to CLI/API/socket without changing either side's logic.

### D2 - Strict layering; memory is a leaf (2026-06-07) — SUPERSEDED by D15
~~Dependencies point interaction -> core -> {memory, agents}; memory is a leaf.~~ Replaced
by an all-to-all mesh. Explainability is preserved by the memory *model* (immutable
graph, derived confidence), not by import restrictions.

### D1 - Compartments: agents, memory, interaction (2026-06-07) — amended by D15, D26
Reorganize the repo from feature folders (store/knowledge/enrich/workspace) into
compartments. Originally four (with `core`); **amended by D15 to three** (`core`
folded away). **Why:** the project's real subsystems are memory, agent dispatch,
and human I/O. Restructuring now is cheap (voice/vision/study not built yet) and
expensive later.

---

### Carried-over hard rules (predate this doc, still binding)

These come from `CLAUDE.md` and stay in force across the refactor:

- **Neo4j is the source of truth**, YAML is seed/import only.
- **Model connection is user-configured (D25).** Every model call goes through one
  chokepoint in `agents`, to whatever connection the user configured (local model,
  inference server, hosted API, subscription-backed CLI, ...); nothing is billable
  unless the user configured a billable connection.
- **Contexts are an entity graph; facts are their own nodes** (provenance is
  first-class).
- **Relationships are weighted** (`weight` on association links; confidence is *derived*
  per claim, never stored on an edge, D38); the learned/neural layer is a layer *over*
  the symbolic graph, never a rebuild of it.
- ~~**Each project is its own graph** (logical isolation; every query scoped by
  `workspace`).~~ **SUPERSEDED by D41:** one global graph; workspace is now a focus /
  importance seed, not a partition.
- ~~**LLM enrichment is staged, never auto-applied**, tagged `claude-extraction`
  with capped confidence.~~ **SUPERSEDED by D53:** machine claims apply immediately but
  land *quiet* (their Source's competence is capped, so derived confidence is capped until
  validated); protection is read-time honesty plus the D30 gate, not write-time staging.
  Machine knowledge stays distinguishable via its Source.
- **Entity focus ("my engine") is inferred from conversation** (resolved in the
  search->recall tool loop, D28/D34), never set by an explicit focus command. *Project*
  focus is the renamed workspace switch and IS set by navigation (`activate`,
  "open project cressida", D41/D50); this rule never covered that.
- **No silently-chosen voice or embedding stack.**

## Open questions (not yet decided)

(Pruned in D53: learned-weight placement was answered by D29 (internal to `memory/graph/`),
intent classification by D37 (the orchestrator role's parse).)

- **Session identity** (load-bearing: focus, push targeting, and recall activation all key
  on it; D34/D45f/D51f). What bounds a session across simultaneous adapters (mic + screen)?
- The **spreading-activation algorithm**: budget unit, fan-out/hub normalization, cycle
  handling, lit threshold (Stage-1 build, D52).
- **Entity resolution**: match-or-create semantics on `entity` names; alias/coref handling
  under append-only, which cannot merge nodes (D51e). (Sources resolve the same way,
  match-or-create on name-or-id, D54e; the open part is the matching itself.)
- **Qualifier match semantics** beyond Stage-1 exact-match (D46/D52).
- The **rich-get-richer / canalization guard**: keep correct-but-rarely-asked facts from
  being starved by popular ones (confidence outranks weight on safety-critical specs, plus
  a little exploration). Note the recall-time nudge also **resets decay clocks** (D53), so
  worn paths both gain weight and stop decaying, a compounding effect Stage-1 measurement
  must watch (D57h).
- The **sentiment-magnitude carrier**: how the sentiment agent's reward sign/size
  (ridicule, emphasis) is delivered into a resolution (a field on `remember` vs its own
  op); decide when reward turns on, Stage-1 step 3 (D53).
- **Importance bookkeeping**: per-anchor contributions vs full re-propagation when an
  anchor changes (D53).
- **Budget exhaustion semantics** (D47): who enforces the Task `budget` (the worker loop
  vs the model wrapper), and what a mid-task kill does with partial findings
  (remember-and-stop vs discard). Decide at build; freshness is unaffected either way
  (attempts stamp at dispatch).
