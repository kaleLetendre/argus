# Memory type: graph

> Status: draft. The **graph** memory type (one of memory's typed MCP servers, D29; see
> [../design.md](../design.md)). The type we are researching first: a reward-driven
> Hebbian connection network. Its MCP tools are in [mcp.md](mcp.md); its deep model in
> [memory-model.md](memory-model.md). Whether this type is even viable is an open
> research question, not an assumption.

## Purpose

Be an explainable, self-learning memory for Argus. Store what is known with provenance,
answer recall queries with sources and a derived confidence, and grow/maintain itself
over time (study). This is the part that must stay trustworthy: a wrong torque spec is
dangerous, so every answer traces back to a fact node with sources and a derived
confidence, and the reward weighting must keep mere agreement from becoming truth (D38/D32).

See [memory-model.md](memory-model.md) for the deep model: weight + derived confidence +
competence (D38), Questions and Events, append-only knowledge, the study loop, the
query/intake pipeline.

## Owns (responsibilities)

- **The graph.** Facts and entities as nodes, links between them. Three values (D38):
  **weight** on links (reachability, use-driven), **confidence** *derived* per claim from
  its attestations × source **competence** (trust). Distinct entities + inheritance carry
  identity; provenance is recorded as attestations (who asserted what). Schema, constraints,
  indexes, import.
- **Recall.** Execute a structured `QuerySpec` (an agent's `recall` tool call): spread by
  **weight** (reachability, budgeted), rank by **derived confidence**, discounted by
  attached Questions. Returns ranked facts with provenance.
- **Intake / write policy.** Apply an `Assertion` (an agent's `remember` call): create
  immutable claim nodes, wire associations, record an attestation. Append-only, never
  edit/delete; prune only what is fully cold *and* unimportant (lifecycle §4). Weight then moves on use, confidence re-derives
  from attestations × competence.
- **Questions and Events.** Mint Question nodes (uncertainty/reward loop) and track Event
  nodes (pending real-world outcomes); resolve them, minting Sources. See
  [memory-model.md](memory-model.md), [lifecycle.md](lifecycle.md).
- **Conversational focus.** "My current engine" is **per-session working memory** (D34):
  transient activation over the shared graph, keyed by session, never global graph state,
  so concurrent sessions and pooled workers never collide. Memory holds it per session.
- **Study / consolidation.** memory's autonomous loop (D33): pursue the reward gradient
  (curiosity), research and self-test to earn confidence, fire due Event follow-ups, propose
  associations, prune the fully-cold-and-unimportant, and bank unresolved items as
  questions for the user.
  Calls agents to reason via the queue plane. Lives here (D15), not a separate coordinator.
- **Self-learning.** Two reward channels (D38): use moves **weight** (nudged at recall
  time on the returned paths, D53); validation mints Sources + moves **competence**
  (re-deriving confidence). Decay on a clock. The weighting maximizes being right, not
  being agreed with (D38/D32).

## Explicitly NOT responsible for

- Parsing natural language. The agent emits `recall` / `remember` tool calls directly
  (D28); memory executes them.
- Being the only thing that can call a model, but note memory *may* enqueue a reasoning
  job for an agent (study) on the queue plane.
- Any user I/O.

## Internal structure (current -> target)

| Now | Target |
|---|---|
| `store/neo4j_store.py`, `store/importer.py` | `memory/graph/` |
| `workspace/models.py`, `workspace/loader.py` | `memory/graph/` |
| `workspace/session.py` (focus/mentions) | `memory/graph/` (focus = per-session working memory) |
| `knowledge/query.py` (lookup core) | `memory/graph/` |
| `enrich/extractor.py` (proposal parse/stage) | `memory/graph/` write side + study |
| `workspace/registry.py` | delete (already dead) |

## Speaks (contracts)

- [agents -> graph memory (MCP)](mcp.md) — the recall / remember / search / neighbors
  tools.
- memory -> agents reasoning (study): a queue-plane job, not a contract here; see
  [../../runtime-topology.md](../../runtime-topology.md).
- [memory <-> interaction](../../contracts/memory-interaction.md) — live graph view +
  ambient notifications only (questions/follow-ups to the user go via agents'
  `push`, D40/D50).

## Invariants (must always hold)

- One global graph (D41); `activate` sets focus, which biases relevance/importance, not a
  hard partition.
- Knowledge is append-only; provenance is first-class; the graph stays inspectable
  (weight and confidence are visible numbers, not hidden embeddings; D8).
- The model must keep popularity/agreement from becoming truth (D38/D32): use moves only
  weight (reachability); confidence is derived from sources, so a wrong-but-worn answer that
  keeps getting corrected loses confidence (its sources' competence drops) while staying
  reachable.
