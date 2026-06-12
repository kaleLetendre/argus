# Runtime topology: processes, tasks, and scaling

> Status: draft (active design, 2026-06-08). Extends the compartment specs
> ([interaction](interaction/design.md), [agents](agents/design.md), [memory](memory/design.md)) with the
> *runtime* shape: how the systems run as **separate processes**, how
> agent work is dispatched as **tasks**, and how the whole thing **scales** from
> one machine to a distributed deployment. Captured in decisions D18-D22 (see the
> master [architecture doc](architecture.md)). Diagrams:
> [architecture.drawio](architecture.drawio).

## Why this doc

The compartment specs say *what* each compartment owns. This says *how they run*.
The driving requirement (from the design conversation): the compartments must be
able to live on different machines (some agents local, some in a rented datacenter
slot, memory on a rented storage server) and be swapped or changed independently.
That only works if they never share code, only messages. So:

> **Each compartment is its own process. The only thing that crosses a boundary is
> a serializable message defined by a contract, never a live object. Placement is
> fully symmetric: any compartment may run on a separate machine or on the same
> machine as another, purely by configuration. No compartment may assume it is
> co-located with another, and none may assume it is remote.**

This is the property that makes "rent a datacenter slot for some agents" a config
change instead of a rewrite.

## Processes, not modules (D18)

Each system is an independently deployable process. Today there are three (more, e.g.
sensors and actuators, can be added later through their own contracts):

- **interaction** (one per device: mic, screen, phone REPL, ...).
- **agents** (the responder; later a pool spread across machines).
- **memory** (the single knowledge authority, fronting Neo4j).

They communicate only through their contracts ([interaction <-> agents](contracts/interaction-agents.md),
[agents -> graph memory](memory/graph/mcp.md), [memory <-> interaction](contracts/memory-interaction.md)).
A contract is transport-agnostic: in-process call, local socket, or network RPC are
all just adapters behind the same message shapes. Because the processes never import
each other, the old circular-dependency worry simply does not exist; nobody can
reach into anyone else's internals.

See diagram **page 1 (Compartments and contracts)**.

## Two initiators, one responder (D19)

Only two things ever *start* activity. The third only ever *responds*.

| Compartment | Role | Woken by |
|---|---|---|
| **interaction** | initiator | input (a human speaks / types) |
| **memory** | initiator | a clock (the study loop ticks) |
| **agents** | responder | being handed a task (by either initiator) |

So there are exactly **two loops**:

- **the interaction loop** lives at interaction: input arrives, interaction hands it to agents,
  renders the reply.
- **the study loop** lives in memory: the timer ticks, memory consolidates and
  hands reasoning work to agents.

agents has no loop of its own. Its "loop" is just "handle the next task." It is the
seat of the thinking, but it only thinks when summoned. Analogy: agents is the
executive, memory is long-term memory plus the subconscious that studies, interaction is the
senses and the mouth.

**interaction hands work to agents, and only agents.** In the interaction path interaction never
talks to memory; if it did, turn logic would leak into interaction and the separation would
be lost. interaction captures, calls agents, renders. One handoff.

## All agent work is a Task (D20)

Every piece of work agents does, whether it came from interaction or from memory's study,
is the same envelope:

```
Task {
  id:         string                       # unique: reply correlation + idempotency
  mode:       "interactive" | "background" # the interaction pattern (see below)
  reply_to?:  address                      # present iff mode = interactive
  complexity: 0..9                         # background routing hint (ignored for interactive)
  intent:     string                       # turn | extract | research | study | check-in (D55b/D56; quizzer + sentiment are sub-roles, never dispatched)
  context:    object                       # the payload the worker needs
  schema?:    object                       # expected structured output, if any
  budget?:    { tokens?, seconds? }        # background bound (D47); defaults from policy
}
```

The two **modes** are named for the *interaction pattern*, not for who produced the
task or what it is about. Purpose ("turn", "study") is exactly the part allowed to
change as interaction and memory evolve, so the envelope never names it. The invariant is:

- **interactive** = a producer is waiting for a result. Carries a `reply_to`. Higher
  priority. (Today: a turn from interaction.)
- **background** = fire-and-forget. No `reply_to`; results land as side effects (a
  write into memory). (Today: study from memory.)

A brand-new producer, or a totally different memory implementation, just emits an
`interactive` or a `background` task. Nothing in agents needs to know what it is.

## The queue feeds the agent pool; memory stays request/reply (D21)

**The queue is the ingress to the (background) agent pool.** Producers drop tasks;
agent workers pull them. This is what decouples *what work needs doing* from *which
worker, where, does it*, which is exactly what lets the agent side be a pool spread
across machines. You add a datacenter worker by starting a process that subscribes
to the queue; nothing in interaction or memory changes.

**memory is not queue-fed.** It is a request/reply authority, like the database it
fronts. You do not put a broker in front of your database; there is one authority
and nothing to distribute. So the asymmetry is deliberate:

> **memory = request/reply authority. agents = (background) queue-fed worker pool.**

Not everything is a queue. The queue is specifically how you feed the part that is a
pool and does slow, distributable work.

### Interactive gets reserved capacity; background goes through the queue

The two modes are isolated so that background load can never starve the interactive
path (a human is waiting on interactive and nobody is waiting on background).

- **Interactive: a reserved set of resources it can always draw on.** A capacity
  guarantee. Reached by **direct request/reply** (not the broker), so a turn never
  depends on broker health and never queues behind background work. Whether the
  interaction path also survives a network outage is a **placement** question, not a
  property of this reservation: co-locate the memory authority with the interactive
  node and recall keeps working through an outage; place it remotely and recall
  depends on that link. The reservation guarantees *capacity*, not *connectivity*.
- **Background: the broker, a shared/scalable pool.** No latency guarantee, retried
  on failure, runs when there is slack.

Start with a strict partition (the interactive worker does only interactive, so it
is never busy when a person speaks). You can relax it later (an idle interactive
worker steals background work, but only if background tasks are small and
preemptible).

### Two research lanes: user-requested before self-directed study (D33)

Within background work, research splits into two lanes with **strict priority**:

- **User-requested research** (high): the user asked something that needs a result;
  drained first, always.
- **Self-directed study** (low): memory's curiosity (the study loop, D33) populates this
  from its own state; it runs only on the slack, in small/preemptible chunks so it yields
  instantly to a user request.

So curiosity is **strictly non-intrusive**: it can never make the user wait. Results route
differently, user-requested surfaces back to the user (the task's final side effect is a
`push(Prompt {kind:"result"})`, delivered live or queued; background tasks never carry a
`reply_to`, D55c); self-directed lands as provisional graph updates plus proactive
questions. This is the reserved-vs-background pattern applied
one level down, inside research.

See diagram **page 2 (Task routing)**.

## Background routing by complexity, mapped to a model (D22)

A background task carries a `complexity` flag (0-9). A **complexity router** maps it
to the right model: trivial work goes to a small/cheap/fast model, hard work goes to
a big model. Nobody is waiting on background, so you can afford to right-size every
task, and that is where right-sizing pays off most (you do not burn the big model on
a trivial extraction).

**The task declares complexity, never a specific model.** Complexity is an intrinsic,
stable property of the work; *which model that maps to* is system policy that changes
as models come and go. If a producer pinned "use model X" you would re-break it every
time the model lineup changed. Declaring complexity and owning the mapping centrally
means you can swap models, add a tier, or move a band to another machine without
touching any producer. (Same principle as naming tasks by interaction pattern, not
purpose: the task describes what is invariant, the policy stays swappable.)

The mapping is a **configurable policy**. First cut, with two models:

```
complexity 0-4  ->  small model
complexity 5-9  ->  big model
```

Later: refined band boundaries derived from testing, more tiers, and per-deployment
overrides through settings. The defaults are a starting point, not a commitment.

Interactive tasks **skip** the router: their guarantee is *availability*, not
*right-sizing*, so they always use the reserved capable resource regardless of
complexity.

### Task identity: correlation and idempotency

Every task carries a unique `id`, for two reasons, both because a queue can deliver
or retry more than once:

- **correlation** (interactive): match a result back to the specific request waiting
  on it.
- **idempotency** (any): memory is append-only, so a re-run background task would
  double-write without a dedup key. (Same instinct as the current enrich code
  deduping proposals on a content signature, now at the task boundary.)

## Scaling: one machine to distributed

The point of all of the above is that scaling is **adding workers and moving
endpoints**, never restructuring. The contracts and the Task envelope are identical
at every stage; only *how many* workers exist, *where* they run, and *which
transport* each edge uses change. See diagram **page 3 (Scaling stages)**.

### Stage 1: one machine (development, or a single garage PC)

Everything on one box. interaction (keyboard REPL), one agents process with a single worker,
memory + Neo4j. The "queue" is degenerate (a queue-of-one, or even a direct call).
The single worker handles both modes, with interactive prioritized.

- **A turn:** interaction -> agents worker -> memory (recall) -> reply -> interaction.
- **A study:** memory's timer ticks -> emits background tasks -> the same worker
  picks them up when idle -> writes results back to memory.

This is the whole system, working, with no broker and no pool.

### Stage 2: split the pool (one or two machines)

Introduce the real split. **Reserve one worker for interactive only** (never blocked),
reached by direct request/reply. Add **background workers** that pull from a real
**broker**. Complexity routing now bites: simple background tasks go to a small model,
hard ones to a big model. memory still local.

- The interactive path is now guaranteed responsive no matter how much study is
  happening, because its capacity is reserved.
- Background throughput scales by adding workers, independent of the interactive path.

### Stage 3: distributed (the target deployment)

Move endpoints; nothing else changes.

- **Garage machine (local):** interaction, the reserved interactive worker, a small model.
  Answers at local latency. (If recall must survive an uplink outage, place the memory
  authority on this box too rather than remote, see resilience below.)
- **Datacenter slot:** the background worker pool and the big model, pulling from the
  broker. Scalable, can be slow, can lag.
- **Storage server (one example placement):** the memory authority (Neo4j), the source
  of truth. It could equally sit on the garage box; placement is configuration.

Each edge is now a network RPC instead of an in-process call, which is purely an
**adapter swap**: same contracts, same Task envelope, same message shapes. What
changed is configuration (endpoints) and transport, not architecture.

- **A turn, distributed:** garage interaction -> local interactive worker -> memory authority
  (recall over the network) -> reply, all local-latency.
- **A study, distributed:** memory (storage server) emits background tasks to the
  broker -> datacenter workers pull them -> big model reasons -> results written back
  to the memory authority.

**Resilience:** surviving a network partition is a **placement** choice, not a
built-in feature (D23). Co-locate the memory authority with the interactive node and
interactive recall keeps working through an uplink outage (background tasks queue
until the link returns); host memory remotely and interactive recall depends on that
link. There is no replica or cache mechanism in the core design.

## Resolved decisions

All earlier open points are decided; none remain open in this doc.

- **Placement is symmetric (D23).** Any compartment runs on a separate machine or the
  same machine as another, by configuration alone. No compartment assumes co-location
  or remoteness.
- **Resilience to a network partition is a placement choice, not a built-in
  mechanism (D23).** There is no replica or cache in the core design. If on-site
  recall must survive an uplink outage, place the memory authority on the interactive
  node; otherwise host it remotely and accept the link dependency. The contracts and
  Task envelope are identical for every placement.
- **Broker: NATS (JetStream) (D24),** behind a transport adapter so it stays
  swappable. One piece of infrastructure covers both the background work-queue and the
  later memory->interaction notification pub/sub.
- **Transport security: mTLS on every edge that crosses a network (D24),** with a
  per-service identity; loopback / in-process edges are exempt. The broker and the
  memory authority require authenticated clients. Certs/keys live in `.env`/secrets,
  never committed.
- **Interactive capacity is strictly reserved: no work-stealing (D24).** Background
  tasks are authored in small chunks so work-stealing could be added later as an
  opt-in, but the reservation is never weakened by default.
- **Interactive stays direct request/reply (D24),** never promoted onto the broker.
  Revisit only if live turns must be distributed across machines.
- **Complexity is a configurable policy with a fixed rubric (D22, D24).** Bands default
  to `0-4 -> small`, `5-9 -> big`, overridable in settings. The 0-9 scale is anchored:
  `0-2` trivial (format / lookup), `3-4` simple (single-fact, one hop), `5-6` moderate
  (multi-fact synthesis, adjudication), `7-9` hard (deep reasoning, research, novel
  associations).
