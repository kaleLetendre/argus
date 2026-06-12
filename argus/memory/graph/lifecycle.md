# Graph memory: lifecycle and value-change reference

> Status: draft (active design). The precise mechanics: how Facts, Questions, and Events
> are created, traversed, resolved, decayed, and deleted, and exactly what moves every
> value. The *why* is in [memory-model.md](memory-model.md). **Rates and thresholds are
> open dials** (tuned on usage); this fixes mechanisms and directions, not numbers.
>
> Two earlier tensions are now **resolved by the un-fuse (D38)**: (1) *does use strengthen?*
> -> yes, use moves **weight** (reachability), which is safe because **confidence is
> separate and derived**, so popularity cannot bleed into truth. (2) *strength on links or
> nodes?* -> **weight on links; confidence derived per claim**.

Dials: `lr` (learning rate), `decay`, `ε` (close/prune threshold), `margin` (contested
band), `cap_*` (provisional caps).

Threshold note (D53): with competence in `[0,1]`, a single source's derived confidence
ceilings at `tanh(1) ≈ 0.76`, so every "high-confidence" bar (surprise detection, the D30
gate, the D51c update guard) must sit below that, or single-source claims can never trip it.

---

## 1. Node creation

**Fact / entity / concept nodes** at **intake** (`remember(Assertion)`):
- the claim is a **structured** `{entity, attribute, value, unit?, qualifier?, claim_type?}`
  (D44/D46/D54, the agent supplies it + a `mode: assert|update` + optional `supersedes`;
  `claim_type` is empirical|derivable, default empirical, and drives the quality-ladder
  fork + the D49 guard; original `text` kept for display). It becomes an immutable **Fact** node (append-only), unless an identical claim already exists on `{entity, attribute, value, unit, qualifier}` (D59b: 18 Nm is not 18 ft-lb), in which case the write **attests the existing node** instead of minting a duplicate (claim-level match-or-create, required by D57b's one-attestation rule, D58h); an `update` adds a
  **supersedes** edge to the prior value (state change, recency wins, no false conflict, D46),
  **unless it contradicts a high-confidence non-user-attested claim, in which case it mints a
  low-urgency Question instead of silently overwriting** (D51c, no destruction bypass);
- new referenced entities are created (memory **match-or-creates** `entity`/`value` names,
  D51e); recurring terms become concept nodes **lazily**;
- **association** edges wire it to its concepts, born at **low weight**;
- an **attestation** edge from the **Source** carries polarity (+1/−1); the claim's
  **confidence is then derived** from its attestations × source competence (nothing stored).
  **Attestation is idempotent (D59a):** one attestation per `(source, claim, polarity,
  via)`; a repeat refreshes timestamps and nothing else, so re-stating or re-ingesting the
  same thing never raises truth. **A source can retract (D62a):** an attestation with the
  same `(source, via)` and **opposite polarity supersedes** the prior one (latest polarity
  wins per origin; the old edge is kept as history, excluded from the confidence sum), so
  assert -> deny -> reaffirm never self-cancels to a permanent zero. **Cross-via collapse (D60c):** a direct attestation with
  the same `(source, claim, polarity)` **supersedes** the `via:"machine"` one (reading the
  document validates the extraction), never adds to it: one origin, one contribution.
  A new source's competence is **born from its type** (D42: manual/paper/spec high, the user
  medium-high, forum low; the agent supplies `source_type` at the Source's first creation,
  unknown -> low prior, D55a), so a single-source claim's cold-start confidence is
  `tanh(competence × polarity)` of that one source (D51d). A **machine-extracted**
  attestation (bulk ingestion) keeps `source` = the document but carries `via:"machine"`,
  and its contribution to the confidence sum is capped at `cap_provisional` until a
  validation touches it (extraction fidelity is not document reliability, D57c);
- **granularity** is the agent's call: a distinct thing is its own entity (built 2JZ vs
  model 2JZ) with an `IS-A` edge for inherit-and-override. **Source granularity (D63a):**
  a Source is the specific **speaker or document**, never the platform: a particular forum
  user, a specific manual edition. The platform only sets the type prior (forum -> low).
  Independence, track record, and retraction (D62a) all key on the speaker.

**Source nodes** are also **minted on resolution** (Sections 5, 6b): an experiment, finding,
or user statement that settles a Question/Event becomes a first-class Source attesting the
winner. The graph grows its own evidence.

**Event nodes** are **created by the agent** at intake when the user describes a pending
real-world outcome (Section 6a).

---

## 2. Question creation (memory-minted, never agent-called)

| Trigger | Where | Signal |
|---|---|---|
| contested recall | answer-time | top candidates within `margin` **and structurally contradicting** (the D60a test: same `{entity, attribute, qualifier}`, different value/unit/polarity, D64a); qualifier-distinguished candidates ("18 cold" vs "13 hot") are **disambiguation** for the agent, never a contest |
| weak best | answer-time | best candidate's discounted confidence below the bar |
| gap | answer-time | nothing matched |
| **surprise** | intake (`remember`) | new claim contradicts a high-confidence belief |
| latent conflict/gap | study | consistency scan |

Cheap and liberal; salience emergent (Section 7 prunes the unimportant). **Where LLM
judgment lives (D64b):** every check in this file is pure field comparison, no meaning.
The judgment happens at **intake** (the extractor structures and normalizes the claim,
units included where unambiguous) and **post-recall** (the orchestrator reviews a flagged
contest before speaking and may close a false one immediately: a unit conversion is the
same spec, an equivalence / D63b close). Unit-conversion false contests are an accepted
Stage-1 cost. Semantic contradictions beyond structure are **study's** job, and study
surfaces them by **writing the normalized claim** so the surprise detector mints the
Question structurally (the agent never mints directly, D64c). Before minting,
memory **searches for an existing open Question matching the contest** on `entity`+`attribute`
(D44) and **refreshes** it instead of duplicating (dedup, D43). The search also matches
**closed** Questions on the same key: a closed hit is never refreshed; the new Question
instead gains a **reopens** edge to the cold one (this is what creates Section 5's reopen
pointer, D58g). Dedup sees only lineage **heads**: a superseded Question is invisible to
it (D58e). A Question is a snapshot of
the contest: **candidate** edges (weight ≈1), **source** edges (≈0.2), **about** edges (≈0);
**uncertainty** from how close/weak the contest is; **importance** inherited from connected
nodes; and a **prediction is snapshotted** on it as a pair
`{presumptive: claim-id | none, confidence}` (D58a: the outcome operand compares
*identities*, so the number alone is not enough): for a recall-born Question, the
**top-ranked candidate and its raw confidence at mint time** (memory's presumptive answer;
it cannot know what the agent later commits, D54b); for a surprise, the **prior belief
claim and its confidence** (D45); for a **gap-born or study-found** Question, `{none, 0}`
(nothing was believed, so any resolution is maximal information; outcome = 1, D57f/D58a);
a **reframe inherits** its parent's snapshot and a **decompose child starts `{none, 0}`,
re-snapshotting at first recall** (D58c). Needed for prediction-error reward. Surprise is detected
**structurally**, as the complement of the D59b match key: same
`{entity, attribute, qualifier}`, different `(value, unit)` or polarity, vs a
high-confidence claim (D60a: 18 Nm vs 18 ft-lb IS a conflict even though the value
matches; no
model; D44). A surprise Question points at two candidates, or at **one** for a bare
denial (same content key, opposite polarity, which claim-level match-or-create routes to
the same node): the contest is then the node's own polarity-mixed attestation sum, the
snapshot its pre-denial confidence, and outcome = 1 if the prior belief survives, 0 if
its derived confidence **fails to remain positive** (sum ≤ 0 counts as overturned, so the
exact tie is defined, D61c/D62b). Read it the way it is meant (D63c): the denial Question
means "**the source says not-X: what is it actually**": it keys on the attribute, so any
later value resolves it; the one-candidate polarity sum is just its storage form. It usually closes in the same step.
(Same-step closure is just Section 5 applied to the minting claim: it closes only if that
evidence's ladder rung drops uncertainty below `ε`, typically a real-world result or a
competent user on an empirical claim; a weaker assert leaves it open, discounting its
candidate(s), which is the question-the-user stance, D32. A surprise-minting `remember`
carries no `resolves_ref`, the Question does not exist before the call, so its same-step
rung comes from `source_type` x `claim_type` alone, no `rigor` field, D58h.)

**Revision lineage (D57a):** reframe/decompose children **inherit the lineage's attempt
count** (counted against D47's cap, which covers `revise_question` chains, not just
research-minted Questions); past the cap, only park or abandon. A **parked** Question
(awaiting the user / the world) is exempt from study dispatch and ask-spacing pressure but
stays alive, keeps discounting its candidates, and closes normally via
`resolves_ref`/topic-match; it fades only if its importance does. **Ask-spacing does not
reset across revisions** (lineage-scoped).

**Composition rules (D58):** a **reframed Question is closed-as-superseded** at reframe
time: it stops discounting, is invisible to dedup, and no longer blocks GC; only lineage
**heads** discount, dedup, surface, and count for the GC guard (the Question-side mirror of
D57d). **Decompose is for suspect-but-don't-know** (D63c): study suspects condition-dependence
(or multiple parts) but cannot yet assign values; when study **knows** the mapping it
resolves directly by requalification (a false conflict, §5/D63b), no split. On
**decompose**, the parent's candidate-edge weights drop to ~0 and the children take the
discount **partitioned on `{entity, attribute}`** (D61a; qualifier discriminates only when
the candidate carries one): an **unqualified** candidate matches **all** children sharing
its `{entity, attribute}` and splits its weight among them; a **qualified** candidate
matches only the qualifier-equal child; candidates matching **no** child move to an
automatic **remainder child** carrying the parent's own key, born like any child (D61b;
the agent may explicitly abandon it if moot). One contest never discounts a claim twice,
in either direction, and never stops discounting an unresolved one (D58d/D59c). The
parent keeps `uncertainty =
max(open children)` as closure bookkeeping only and **closes silently** when all children
close, or sooner if a child's resolution structurally answers the parent's key, in which
case open siblings **close-as-moot** (cold, kept; a recurrence reopens via the
closed-dedup path, D59d). The parent never runs a Section-5 update of its own. A decompose **child is born with the parent's
uncertainty** (re-derived at its first recall, like its snapshot, D58c). **Park is
reversible (D58b):** `revise_question` has a `resume` action, and study's consistency scan
resumes a parked Question when new evidence touches its candidates (a new attestation or
Event on a candidate claim); park is never a one-way door.
The conflict lives **only** in the Question, never as cross-negative attestations, so it is
not double-counted (D43).

---

## 3. Graph traversal (recall), two stages

1. **Resolve** to entry entities (focus + identity facts; instance overrides type).
2. **Seed** activation (=1.0); activation is transient per-session scratch (D34), never
   written to the shared graph.
3. **Spread by weight**: each hop scales activation by the link's **weight**; worn paths go
   first/farthest; cold ones may not be reached under budget. (Reachability stage.)
4. **Collect** lit candidates matching `want`/`attested_by`/`polarity`.
5. **Rank by derived confidence**, discounted by attached Questions:
   `effective = confidence(claim) × clamp01(1 − Σ_Q uncertainty(Q) × weight(Q→claim))`
   (clamped, D45). A claim with an incoming `supersedes` edge is **excluded**: only chain
   heads compete; history stays reachable on request (D57d). (Truth stage.)
6. Return top-K with provenance.
7. The agent **decides** (D30): answer if top effective confidence clears the bar; else
   research (user-requested lane) or ask. Memory **mints/refreshes a Question** as a side
   effect (Section 2). Lock-free: many sessions traverse at once.

---

## 4. Node decay and delete

- **Decay (weight):** on a clock, each association weight drifts down `weight ·= (1 −
  decay)`. Importance-scaled: a link decays slower if **either endpoint** is important
  (`decay_eff = decay / max(importance(a), importance(b), floor)`, with `floor` an explicit
  dial: low importance means faster forgetting, never one-tick annihilation, D57h). Ambient
  forgetting.
- **Use nudges at recall time, never inflates truth (D53):** links on the path to a
  recall's returned candidates nudge up and reset their decay clock **during the recall
  itself**, while the per-session activation is live (no trail outlives the turn, D34, and
  no outcome report is needed; skipped entirely when the caller passes `nudge:false`,
  background/adversarial roles, D55e). This is *relevance*, not rightness: a returned-but-wrong
  claim keeps its small boost (it must stay reachable to be corrected); its truth falls in
  confidence space, which use cannot touch. This is the resolution of the old "does use
  strengthen" worry.
- **Confidence** is never decayed directly, it re-derives whenever an attestation or a
  source's competence changes.
- **Delete (prune/GC):** a node is deleted only when **cold (low weight on all links) AND
  unimportant**. A node referenced by an **open** Question or Event is never GC-eligible
  regardless (pruning it would strand candidate edges, break the discount sum, and break
  D53's down-nudge handle); it becomes eligible when the referencing Question/Event closes
  or is pruned (D56d). Settled-but-cold-but-important knowledge survives. **Exception (D50, OFF in
  Stage 1 per D52): a *superseded* claim is GC-eligible regardless of importance** (archived
  to a cold store; update-chains compacted), **but GC preserves an attestation stub** (source,
  polarity, value) so provenance and source competence survive the compaction (D51c).
  Append-only: content is never edited; deletion is GC of the unreferenced-and-uncared-for.
  Pruning is **study's** job, off the hot path.

---

## 5. Question resolution

Evidence arrives (research, experiment via an Event, user, or study derivation).
`resolves_ref` **follows a supersedes chain to the lineage head** (an answer to a
since-reframed Prompt lands on the live Question; for a decomposed target it applies to
the child whose key the claim structurally matches, where routing matches **exact** keys,
D62c: D61a's qualifier-optional rule governs the candidate partition only, so an
unqualified resolving claim never multi-matches; if no child matches but the
**parent's** key does, that is the D59d early close (parent closes, open children
close-as-moot, the resolving remember's attestation lands normally, no resolution update
runs through the parent's edges, D60e); if nothing matches, it lands as a plain `remember`
with no resolution, D58e/D59). One
structural update, scaled by **edge weight** and by **prediction error** (|resolved
outcome - the snapshotted prediction|, D43d/D54b; outcome = **1 if the snapshotted
presumptive answer is confirmed, 0 if overturned**, D57f: a confident belief overturned
moves everything hardest, a confident belief confirmed teaches little):

1. **Lower uncertainty** by the evidence's competence × rigor (the claim-type ladder, D53:
   real-world always top; competent-user above studied on empirical claims, studied above
   user opinion on derivable ones; rigor arrives on the resolving `remember`'s `rigor`
   field, D56b; self-earned capped at `cap_provisional`).
2. **Attest the winner** -> the winner's *derived confidence* rises. One attestation, not
   two (D57b): the resolution's attestation IS the resolving `remember`'s match-or-create
   attestation; a **new** Source is minted only when the settling evidence is itself a new
   thing (an experiment, a research finding), never as a second attestation for the same
   observation, and an existing settler (the user) stays ONE Source node (D54e).
3. **Update involved sources' competence** (involved = the candidates' attesting sources
   **as of mint**, excluding the resolving remember's own attestation, so a settler never
   marks itself right for agreeing with itself, D58f; right up, wrong down) -> re-derives
   confidence on every claim they attest (the free retroactive correction, D12).
   **False conflict (D63b):** when the resolution **requalifies** the candidates instead
   of picking one ("18" -> "18 when cold", "13" -> "13 when hot", each superseded by its
   qualified version), the question closes with **no loser**: every involved source is
   marked right, none wrong, and outcome = 1 (the presumptive answer survived in
   qualified form).
4. **Nudge weights**: up on the winner's links, optionally down on the losing candidates'
   links (the Question's candidate edges are the structural handle, D53).
5. **Grow edges** if study implicated new nodes.

Close at `uncertainty < ε` (cold, kept as history). A **re-opening** (later evidence
contradicts a closed resolution) is a **new** Question pointing at the cold one
(append-only); the pointer is the **reopens** edge created by Section 2's closed-Question
dedup match (D58g).

---

## 6a. Event creation and follow-up

- **Created by the agent** at intake: it recognizes a pending-outcome statement ("torqued to
  18 to test", "part arrives Tuesday", "tuning it next weekend") and calls `track_event`.
- An Event carries: **what's pending + what to check**, a **follow-up trigger** (a time
  and/or a context), links to the **Question(s)** it would resolve and the entities involved,
  and **importance**.
- **Follow-up fires** from the **study clock** (a due time) or when the **relevant context**
  comes up; the agent surfaces a check ("did the cam caps hold at 18?") via the proactive
  channel.

## 6b. Event resolution

When the outcome is reported:
1. **Mint a Source** for the **real-world result** (top-of-ladder competence) and attest the
   relevant claim. (One attestation, not two: the minted real-world Source carries it; the
   reporting user is recorded on that Source as provenance, never as a second independent
   attestation, so one observation is not double-counted in the confidence sum, D43b.)
2. **Resolve any linked Question** (Section 5) with that strong evidence.
3. Deliver the **real-world reward** (large prediction-error magnitude if it overturned a
   confident belief).
4. Mark the Event **closed** (cold, kept as history).

---

## 7. Decay and delete of Questions and Events

- **Question liveness** = importance + recurrence: each hit at recall **refreshes** it;
  never-hit-and-unimportant ones **fade** (importance-scaled). Emergent salience, no tuned
  threshold.
- **Event liveness**: an un-fired or un-answered Event re-surfaces on its trigger; if
  repeatedly ignored and unimportant, it **fades** like a stale Question (the system stops
  nagging about things you never report).
- **Delete (both, via study's GC):**
  - *resolved/closed* Question or Event goes cold, kept as history for a window (the
    provenance of how it settled), then pruned once cold *and* unimportant; the minted Source
    and the value changes persist.
  - *abandoned* (never resolved/answered, unimportant, non-recurring) is pruned.
  - pruning a Question/Event drops its candidate/about/source/link edges; the Facts and
    Sources it pointed at remain (independent nodes).

---

## 8. Every value, and exactly what moves it

| Value | On | Up | Down | Notes |
|---|---|---|---|---|
| **weight** | association link | traversal to a returned candidate (recall-time nudge, D53; skipped when `nudge:false`, D55e); a Question resolving **for** it | clock decay (importance-scaled); a Question resolving **against** it (losing candidate, D53) | reachability only; saturating, bounded [0,1]; nudges are commutative scalar bumps (lock-free); **use never touches truth** |
| **confidence** | *derived*, per claim | a new/stronger attestation (e.g. a minted Source); a source's competence rising | a source's competence falling; a contradicting attestation | `squash(Σ independent competence × polarity)`; never stored, never decayed; re-derives live |
| **competence** | Source | being right on a resolved Question/Event | being wrong (magnitude may be scaled by sentiment, e.g. ridicule; carrier open, D53) | **born from source type** (D42); **one scalar in Stage 1, per-topic deferred (D52)**; **user floored, demoted only by real-world/authority (D49)**; a change re-rates its claims **lazily at read time** (D51a, free, no cascade) |
| **freshness** | Question (*derived*) | uncertainty dropped recently | attempts since uncertainty last dropped | **derived stalled-attempt counter (D51b)**, not stored; attempts are stamped at **dispatch time** (when **any** Task carrying the Question id is dispatched, either lane, or a check-in batches it, D58i), since fire-and-forget tasks report no completion; when it **rots**, study reframes / decomposes / parks / abandons via `revise_question` (D48/D56a/D57a; revisions inherit the lineage's attempts, D47-capped); gates meta-review only; ask-spacing keys on a per-Question **last-surfaced-to-user stamp** written via `note_surfaced` on actual Prompt delivery or an inline D30-gate ask (D57e/D58j) |
| **uncertainty** | Question | a **surprise** that births it; new conflicting evidence | resolving evidence (competence × rigor) | in **[0,1]** (D57h); close at `< ε`; never moves from the graph's own confidence |
| **importance** | Fact / Question / Event | an **anchor event** (user "critical", stakes, sentiment emphasis; NOT session focus, D55d); propagation from important neighbors | anchor archived ("sold X / forget X"); slow decay; relevance fading | propagated from anchors; inherited by Questions/Events; not a one-way ratchet |
| **edge weight** | Question candidate/about/source edge | set at birth (candidate ≈1, source ≈0.2, about ≈0); raised if study finds a node more implicated | rarely lowered | scopes both the recall discount and the resolution reward |
| **Event trigger/status** | Event | created on intake; refreshed on re-surface | fires (closed) or fades (abandoned) | time and/or context trigger; the study clock fires due ones |
| **activation** | transient, per session | seeded on `about`; spread by weight | budget cutoff; evaporates at end of turn | never stored (D34); working memory, not a node value |

### Who computes the soft signals
- **Reward sign/magnitude and importance** use a **sentiment agent** (tone) + explicit
  signals (correction/confirmation/real-world result) + stakes (learned cost-of-being-wrong).
- **Competence** is learned per topic from track record on resolved Questions/Events.
- **weight, uncertainty, edge weight, activation** are mechanical; **confidence** is derived.

---

## Cross-references

- Why / conceptual model: [memory-model.md](memory-model.md).
- MCP surface (`recall` / `remember` / `search` / `neighbors` / `activate` /
  `set_importance` / `track_event` / `revise_question` / `note_surfaced`): [mcp.md](mcp.md).
- Decisions: D30 (research-first), D31 (fused, superseded), D32 (user as source), D33
  (study), D34 (per-session focus), D35 (Questions), D36 (importance), D38 (un-fuse), D39
  (Events) in [../../architecture.md](../../architecture.md).
