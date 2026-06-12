# Memory model (graph type): a reward-driven connection network

> Status: draft (active design). The deep model for the **graph** memory type
> (decisions D31-D39). **Three values, not one**: weight (reachability, stored on links),
> confidence (truth, *derived* from sources), competence (trust, stored on sources).
> Uncertainty + reward live as **Question** nodes; pending real-world outcomes live as
> **Event** nodes; **importance** is a separate attention value. Whether this whole thing
> is viable is the central research question, not an assumption. Mechanics:
> [lifecycle.md](lifecycle.md). Role + MCP surface: [design.md](design.md),
> [mcp.md](mcp.md).

## The pieces (orientation)

**Node types:** **Fact** (a claim, entity, or concept; immutable content). A *claim* is a
**structured** `{ entity, attribute, value, unit?, qualifier?, claim_type? }` (D44/D46/D54;
`claim_type` is empirical|derivable, default empirical, the extractor labels it), produced
by the agent at intake, with the original `text` kept for display; this structure is what
lets memory compare claims (surprise, dedup, topic-match) without a model. The agent labels each
write **`assert`** (a claim) or **`update`** (a state change); an `update` **supersedes** the
prior value (recency wins) instead of false-conflicting, unless it contradicts a
high-confidence non-user-attested claim, in which case it mints a low-urgency Question
instead of silently overwriting (D51c). Recall ranks only **chain heads**: a superseded
claim is excluded from ranking, which is how "recency wins" is actually enforced (D57d). Surprise fires only on an
`assert` disagreeing with a high-confidence claim **of the same qualifier** (D46). *Deeply
noted: the claim shape is the design's most likely rework point, a Stage-1 simplification of
temporal/conditional/ambient knowledge.* Plus **Source** (a Fact in its asserting
role: user, manual, experiment, research finding), **Question** (an active, salient
uncertainty), **Event** (a pending real-world outcome to follow up on).

**Edge types:** **association** (fact-fact, carries **weight**), **attestation** (source ->
claim, carries polarity), Question **candidate/about** edges (carry an edge weight), Event
links (to the Question it would resolve and the entities involved).

**Values** (mechanics in [lifecycle.md](lifecycle.md)):

| Value | Lives on | Means | Moves on |
|---|---|---|---|
| **weight** | association link | reachability / relevance | use (recall-time nudge, D53), decay |
| **confidence** | *derived*, per claim | truth | recomputed from its attestations × source competence |
| **competence** | Source | trust / track record (per topic) | being right/wrong on resolved Questions |
| **uncertainty** | Question | how unresolved | evidence (down), surprise (up); never decays on its own (liveness/fading is separate, lifecycle §7) |
| **importance** | Fact / Question / Event | how much it matters (attention, not truth) | anchors + propagation, decay |
| **edge weight** | Question candidate/about edges | how much resolving moves this node | set at birth, grows with study |
| **activation** | transient, per session | what's lit during one recall | seeded + spread, evaporates |

## Three values, not one (and why they can't be merged)

We tried fusing reachability and confidence into a single "connection strength" (D31). It
fails on one critical case: if **using** a path strengthens the fused number, then asking
about something a lot makes it *more confident*, popularity bleeds into truth (the
illusory-truth effect). For safety-critical specs that is the exact failure to avoid. So
they stay separate (D38):

- **weight** (on association links) = **reachability**, use-driven. Drives spreading
  activation. Frequently/well-used paths get strong and surface fast. This is the Hebbian
  "fire together, wire together" channel.
- **confidence** (derived, per claim) = **truth**, computed:
  `confidence(claim) = squash( Σ over independent attestations: competence(source) × polarity )`
  (`squash` = `tanh` placeholder, D45). One attestation per `(source, claim, polarity, via)`:
  re-statement refreshes, never adds (D59a), a direct attestation supersedes its
  via-machine twin (D60c), and an opposite-polarity attestation from the same origin
  supersedes the prior one (latest wins; a source can retract, D62a), so repetition
  cannot raise truth and retraction cannot permanently zero it. Never
  stored, never nudged. Asking a lot adds **zero** sources, so use cannot move it.
- **competence** (on sources) = **trust / track record**, per topic. **Born from the
  source type** (D42: factory manual / spec / peer-reviewed paper ~high; experiment ~high
  by rigor; the user ~medium-high and topic-dependent; forum / random web ~low), then moves
  only on validation (being right or wrong when a Question/Event resolves). So a single-
  source claim's **cold-start confidence** is `tanh(competence × polarity)` of that one
  source (competence in `[0,1]`; **Stage 1 = one scalar per source, per-topic deferred**,
  D51/D52).

This keeps relevance-learning-from-use (weight) AND honest confidence (derived), which one
fused number cannot do at once. It also restores **retroactive correction for free**:
because confidence reads each source's *live* competence, fixing one source re-rates every
claim it attested (D12).

## The reward signal: two channels, routed correctly

A returned memory has two effects, routed to two different values so they never collide:
relevance is paid at recall time, truth waits for validation (D53):

- **Reachability (weight):** the links a recall traverses to its returned candidates nudge
  **up at recall time**, while the per-session activation is still live (D53; easier to find
  next time, and no trail has to outlive the turn). This is *relevance*, not rightness: a
  returned-but-wrong claim keeps its small boost (it must stay reachable to be corrected);
  its truth falls in confidence space. **Down** is decay plus a Question resolving against
  it. Usage, never truth.
- **Truth (confidence, via competence):** a **validated** outcome **mints a Source** and
  updates **competence** (right sources up, wrong ones down), which re-derives confidence.
  Validation, never popularity.

Magnitude is roughly **prediction error**: a confident answer that turns out wrong is a big
hit; an uncertain one resolved teaches the most; a confident-and-right one teaches little.
Reward sources by quality (the ladder, **claim-type-dependent**, D53): a real-world result
is always the top; on **empirical** claims competent-user-confirmed outranks studied
(derived/cross-checked/quizzed), on **derivable** claims studied outranks user opinion;
below both sit read-one-source, then mere-acceptance; correction and ridicule punish; decay
forgets. **The weighting is the experiment.** Ridicule/emphasis come from a **sentiment
agent** reading the user's tone.

## The user is a source, not the ground truth (not a sycophant, D32)

The user is a high-but-**topic-dependent** Source: near-authoritative on what they own and
did, weak on what they are asking to learn. Their competence is per-topic, learned from
track record / certainty / telling-vs-asking. Argus **questions the user** when input
conflicts with well-studied knowledge (D30), holds its ground in teaching mode, and treats
**real-world results as outranking opinion.** The reward weighting maximizes *being right*,
not *being agreed with*. **The user is a competence special case (D49):** their competence is
**floored**, and on **empirical** claims about their own domain it drops **only** on a
real-world outcome or a genuinely authoritative source, never on mere research disagreement,
so the assistant cannot self-train into distrusting the user, and a user *state change* (D46
`update`) is a supersession, not the user "being wrong."

## The quality ladder (how much an outcome grants)

The ladder is **claim-type-dependent**, not one total order (D53). A real-world result is
always the top; between them, **studied** and **competent-user-confirmed** swap places by
claim type:

```
              empirical claims (a torque)        derivable claims (a derivation)
strongest     real-world result                  real-world result
              competent-user-confirmed (D49)     studied: derived + independent cross-check
                                                          + survived adversarial quizzing
              studied (can read, not settle)     competent-user-confirmed
weak          read one source                    read one source
weakest       mere acceptance                    mere acceptance
```

- **Independent corroboration only.** Ten posts copying one origin count as one source.
- **The earned rung travels on the resolution**: a resolving `remember` carries
  `rigor: "read-one" | "cross-checked" | "quizzed"` (D56b), so memory can tell a
  survived-quizzing studied result from a casual extraction without reasoning.
- **Machine-extracted attestations are capped** (D57c): bulk-ingested claims keep the
  document as their Source but carry `via:"machine"`, contributing at most
  `cap_provisional` until validated. Extraction fidelity is not document reliability: a
  misread spec must not land at manual-grade confidence.
- **Derivable vs empirical is why the ladder forks.** A derivable claim can be settled by
  study itself: a derivation that survives adversarial quizzing is its own ground truth,
  and holding studied ground in teaching mode is the anti-sycophant stance (D32). An
  empirical claim (a torque) can only be settled by the world or by the person who owned
  and did the thing; research can read about it but cannot settle it, which is exactly why
  research disagreement cannot demote the user there (D49). The **extractor labels** each
  claim (`claim_type`, default empirical, D54a); memory just reads the label, so the fork
  costs no model call on the hot path.

## Questions: uncertainty + the reward loop, as graph nodes

A **Question** node is a salient, active uncertainty crystallized into the graph. One
structure, four jobs: **eligibility** (reward attaches here), **curiosity** (study works
the highest `uncertainty × importance`), **proactive questions** (the unresolvable ones get
asked), **resolution provenance** (a closed Question + its minted Source).

- **Born** (memory-minted, never agent-called) from a contested recall / weak best / gap,
  or an intake **surprise** (detected *structurally* in `remember`: same entity/attribute,
  different `(value, unit)` or polarity, same qualifier, vs a high-confidence claim,
  D43/D60a), or a study-found latent
  conflict. Memory **searches for an existing matching Question first** and refreshes it
  rather than minting a duplicate (dedup, D43).
- **A conflict is the Question, not cross-negative attestations** (D43): competing values
  stay separate claims with their own positive support, so the contest is penalized once
  (the discount), never double-counted against derived confidence.
- **A prediction is snapshotted** onto the Question/Event (D43/D45/D54b): a Question/Event
  is not an immutable Fact, so it may store values. The snapshot is a **pair**: the
  presumptive candidate's id and its confidence (D58a, the outcome operand compares
  identities). For a recall-born Question it stores the **top-ranked candidate and its raw
  confidence at mint time** (memory's presumptive answer; the agent's commit happens after
  recall, so memory cannot know it). For a born-and-closed
  **surprise**, it stores the **prior belief's** confidence (before the contradiction), else
  prediction error would be trivially zero exactly where it should flip hardest. Resolution
  **consumes** the snapshot: its update magnitudes scale by prediction error (prediction vs
  resolved outcome, lifecycle §5).
- **Wired** as a snapshot of the contest: **candidate** claims (edge weight ~1), their
  **sources** (~0.2), **topic** seeds (~0); edges grow with study.
- **Recall discount:** a claim's confidence is lowered by attached Questions,
  `effective = confidence × clamp01(1 − Σ uncertainty(Q) × weight(Q→claim))` (clamped so
  accumulated uncertainty can't go negative, D45), so contested facts come back quiet ->
  trips the research/ask gate (D30).
- **Resolution = reward, structurally:** evidence lowers uncertainty, **mints a Source**
  attesting the winner (raising its *derived* confidence), updates sources' **competence**,
  and nudges the used **weights**. Close at `uncertainty < ε` (cold, kept as history). A
  surprise is usually born-and-closed in one step (big prediction error); it closes
  same-step only if the minting evidence itself clears `ε` (lifecycle §2), else it stays
  open and discounts both candidates.
- **Salience is emergent:** cheap to create, decay prunes one-offs, recurrence + importance
  keep the rest warm. No tuned creation threshold.
- **Freshness + meta-review (D48):** a Question has a **derived** freshness counter that
  rots on unresolved research attempts and refreshes on genuine progress (D51b; surfacing
  to the user feeds the separate ask-spacing stamp, D57e). When it **rots**,
  study hands it to an agent that **reframes** it (a better-posed Question supersedes it,
  so the user is never asked a badly-posed question), **decomposes** it into sub-Questions
  (parent/child; resolving parts answers/dissolves the parent), **parks** it (awaiting the
  user / the world: exempt from study and ask-spacing, still alive and discounting, D57a),
  or **abandons** it, via `revise_question`, the one agent-side Question write (D56a).
  Revisions inherit the lineage's attempt count against D47's cap and ask-spacing does not
  reset across revisions, so rework can neither loop forever nor re-arm nagging (D57a). A
  reframed Question is **closed-as-superseded** (only lineage heads discount, dedup, and
  surface, D58e), and parking is **reversible** (`resume`, or study resumes it when new
  evidence touches its candidates, D58b). A
  stale important question is thus reworked, parked, or retired, not nagged
  forever. A light **ask-spacing** backoff caps how often an unresolved question is re-surfaced
  to the user (the question stays alive; the user is asked occasionally). With importance-decay (which culls
  the no-longer-relevant), this closes the nagging doom-loop.

## Events: pending real-world outcomes to follow up on

A **Event** node is the agent's memory of something **happening in the world with a future
outcome it should check back on**: an experiment ("torqued to 18, will it hold?"), a
delivery ("part arrives Tuesday"), a job in progress, a scheduled test. The set of open
Events is "what am I waiting to hear about?", the external mirror of Questions' "what am I
unsure about?".

- **Created by the agent** at intake (it recognizes a pending-outcome statement, unlike
  Questions which memory mints). Carries: what's pending + **what to check**, a **follow-up
  trigger** (a time and/or a context), links to the **Question(s)** it would resolve and
  the entities involved, and importance.
- **Follow-up:** when the trigger fires (the **study** clock fires due Events, or the
  relevant context comes up), the agent surfaces a check ("did the cam caps hold at 18?").
- **Close = the best reward:** the outcome **mints a Source** for a *real-world result*
  (top of the ladder), **resolves any linked Question**, and delivers strong reward. This
  is the mechanism that makes real-world reward actually *flow*, without it, the highest-
  quality signal evaporates because nobody checked back.
- **Abandon:** if never reported, it re-surfaces and eventually decays/prunes
  (importance-scaled), like a stale Question.

Question vs Event: a Question is internal uncertainty resolved by *seeking* evidence; an
Event is an external pending outcome resolved by *following up*. They are siblings (both
open loops tracked until closed, both feed the proactive channel, both yield reward) and
often linked (an experiment is an Event run to close a Question).

## Importance: attention, separate from truth (D36)

**weight/confidence = reachability/truth; importance = how much you care.** Selling the
Cressida drops its importance, not its facts' truth. Importance is **anchored + propagated**
(a few anchors set by the user, painful-error/stakes, or the sentiment agent; importance
flows out across associations). Session focus is **not** an anchor (D55d, amends D36):
focus biases relevance within its own session only, or concurrent sessions would fight
over the shared value; "what I work on matters" is served by weight (use wears paths) and,
if needed, by the agent deliberately raising a `set_importance` anchor from sustained
engagement. Context events re-anchor immediately ("this is
critical" raises; "I sold the X / forget X" archives), cooling only what *depended* on the
anchor. It drives **study priority** (`uncertainty × importance`) and **decay rate**
(important decays slower). Not a one-way ratchet. The agent maps relevance statements to a
`set_importance` directive.

## Recall: two stages, weight then confidence

1. Resolve the request to entry entities (focus + identity facts; instance overrides type).
2. **Spread by weight** from the seeds (worn paths conduct, budgeted), collecting candidates
   (reachability, this is where weight earns its keep, separating the relevant from the
   pile of everything-you-know).
3. **Rank by derived confidence**, discounted by attached Questions (truth).
4. Return top-K with provenance.

Activation is transient per-session scratch (D34, never on the shared graph), so concurrent
sessions recall without colliding. **Structure does identity, weight does relevance,
confidence does truth.**

## Append-only knowledge (D10)

Claims are immutable; a disagreeing value is a new node, the old goes cold (its weight
decays) but is kept as history. The claim *content* never changes and confidence is
derived; outside claim content, the stored values that move are weight, competence,
importance, and the Question/Event scalars (uncertainty, the prediction snapshot, edge
weights, Event status; lifecycle §8). Reads hit immutable nodes (lock-free).

## Study: the offline self-learning loop (D33)

memory's clock loop walks open Questions by `uncertainty × importance`, **researches and
self-tests** (derivations, independent cross-checks, other agents quizzing it), resolves
provisionally (below ground truth), and does housekeeping (decay, prune cold+unimportant).
Research runs in **two lanes, strict priority**: user-requested first, self-directed study on
the slack. **Bounded (D47):** every background task carries a **token/time budget**, the loop
**idles down** (event-driven wake + exponential backoff) when the Question/Event queues are
empty, and research has a **depth/rate cap** so it cannot recursively mint Questions, no
unbounded model spend on an idle machine.

**The check-in (D40):** on its clock, memory also gathers **due Events + top open Questions**
and hands them to an agent (a background task); that agent resolves what it can with its
tools and **pushes the rest to the user** (a proactive question or Event follow-up) via the
interaction `push` op, delivered to a live session or queued for the next interaction. This
is the path that makes proactive questions and Event follow-ups actually reach the user, and
the only way real-world / user-validation reward gets harvested.

## What this supersedes and keeps

- **Supersedes D31** (the fused single strength): un-fused back to **weight + derived
  confidence + competence** (D38), restoring D9/D12.
- **Adds** Question nodes (D35), Event nodes (D39), importance (D36).
- **Keeps** Hebbian-symbolic + inspectable (D8), append-only (D10), research-first (D30),
  anti-sycophant (D32).

## Open questions (the experiment)

- The **reward weighting** and the decay / nudge / discount rates (tuned on usage).
- **Canalization vs exploration** (keep cold-but-correct facts reachable).
- The **intake surprise detector** (reliably spotting a contradiction with a confident
  belief), inside `remember`.
- **Event follow-up timing** (time vs context triggers, how aggressively to nag).
- The **sentiment-magnitude carrier**: how the sentiment agent's reward sign/size
  (ridicule, emphasis) is delivered into a resolution (a field on `remember` vs its own
  op); decide when reward turns on, Stage-1 step 3 (D53).
- **Importance bookkeeping**: "cooling only what depended on an anchor" implies tracking
  per-anchor contributions (or recomputing propagation from all anchors on a change);
  pick at build (D53).
