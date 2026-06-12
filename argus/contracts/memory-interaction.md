# Contract: memory <-> interaction

> Status: draft. The knowledge <-> world edge. Not the main Q&A path (that's
> interaction<->agents); this exists so interaction can **render the graph directly** and memory
> can **push notifications** without routing through agents.

## Parties & direction

- **memory -> interaction:** push graph state / changes for a live view; ambient
  notifications ("study added 3 associations"). Questions and follow-ups that need the
  user go via agents' `push(Prompt)`, never this edge (D40/D50).
- **interaction -> memory:** direct read-only inspection for a UI (browse/zoom the graph)
  that doesn't need parsing or reasoning.

## Transport

- **Now:** unused in the keyboard MVP (no graph UI yet).
- **Later (no contract change):** memory as a service streams to a UI adapter over
  a socket; the Neo4j browser already covers raw inspection in the interim.

## Operations

### memory -> interaction
- `notify(Notification)` — passive, ambient signals for a UI ("study added 3 associations").
  **Questions/follow-ups to the user do NOT go here**: they are phrased and pushed by an agent
  via interaction's `push(Prompt)` (D40/D50), so they are composed/spoken consistently. This
  edge is passive rendering only; `kind:"question"` is dropped.
- `subscribe(view) -> stream<GraphDelta>` — push focus/graph changes so a live
  visualization stays current (the focus subgraph lighting up as the user talks).

### interaction -> memory
- `inspect(scope) -> GraphView` — read-only fetch of a subgraph for rendering
  (nodes/edges with their weight/confidence/competence for display). No NL, no writes.

## Data shapes

```
Notification { kind: "info"|"alert", text, ref? }   # ambient only; questions go via agents' push (D50)
GraphDelta   { added[], removed[], reweighted[], focus[] }
GraphView    { facts[], associations[], attestations[] }   # display projections
```

## Guarantees

- **Read/notify only.** interaction cannot mutate knowledge through this edge; all writes
  go agents -> memory (so the write policy is never bypassed).
- Views are **focus-filtered** over the one global graph (D41, not partitioned) and carry
  the display signals (weight/confidence/competence) so a UI can show *why* something is
  surfaced.

## Errors

- Store unreachable -> the view degrades (empty/stale with a flag); it never takes
  down an interaction adapter.

## Versioning / open questions

- ~~Whether questions-to-the-user are pushed here or routed through agents~~ Decided
  (D40/D50, noted by D53): through agents' `push(Prompt)` for consistent phrasing; this
  edge stays passive rendering only.
- The graph-view projection format for a real UI.
