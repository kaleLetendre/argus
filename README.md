# Argus

A voice-navigable, context-aware assistant. You speak a command
to move Argus into a **context** ("argus, open project cressida"), then ask
questions answered from that context's knowledge ("what's the torque spec on the
cam caps for my current engine").

This repo implements the **knowledge network**: the core that holds contexts as
a weighted entity graph, tracks which one is active and what it's focused on, and
answers questions. Voice (microphones) and vision (cameras) are future layers
that feed into this same core.

## Concepts

- **Workspace / context** — one project (e.g. Project Cressida).
- **Entity graph** — nodes (engine, parts, tools) connected by **weighted edges**
  (`weight` = association strength, `confidence` = how sure we are).
- **Facts** — first-class `(:Fact)` nodes on entities (`cam_cap_torque: 18 ft-lb`),
  each with optional `unit`, `note`, `source`, and `confidence`.
- **Docs** — free-form prose knowledge, searched by RAG.
- **Hybrid retrieval** — a question checks structured facts first (exact), then
  falls back to RAG over the docs.
- **Focus** — "my current engine" is *inferred from conversation*: the most
  recently mentioned engine, or the only one in the project.

## Store

**Neo4j is the canonical store** (the source of truth, with backups). It runs in
Docker, bound to `127.0.0.1`. The YAML under `workspaces/` is a *seed/import*
format used to populate the graph; at runtime everything queries Neo4j.

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
scripts/setup-neo4j.sh        # starts Neo4j in Docker and seeds the graph
python -m argus               # text shell that simulates the voice flow
```

Then type what you'd say:

```
> open project cressida
> what's the torque spec on the cam caps
> what's the firing order on my current engine
> what's the target boost on the turbo      # surfaces low-confidence facts
> how do I set the cam timing               # RAG fallback to the docs
```

Explore the graph visually at http://localhost:7474 (user `neo4j`, password in
`.env`).

## Growing the graph with Claude

Argus can read a project's docs and propose new entities/facts/relationships,
using Claude through the Claude Agent SDK (it reuses the `claude` CLI already
logged in on the box, no API key needed). Proposals are **staged for review**,
never applied automatically, and each cites the exact doc quote that supports it.

```bash
python -m argus.enrich run cressida       # Claude studies the docs, stages proposals
python -m argus.enrich review cressida     # see proposals with their evidence
python -m argus.enrich approve <pid>       # apply one;  reject <pid> to discard
```

In the voice shell, say "study the docs" to trigger the same thing. Applied
proposals are tagged `claude-extraction` with capped confidence, so machine-
inferred knowledge stays distinguishable from what you stated yourself.

## Adding a context

Create `workspaces/<slug>/` with `workspace.yaml` (name + aliases), `graph.yaml`
(entities/facts/edges, with optional `weight`/`confidence`), and any `docs/*.md`.
See `workspaces/cressida/` for the reference example, then re-seed:

```bash
python -m argus.store.importer --reset
```

## Backups

Neo4j is the source of truth, so back it up:

```bash
scripts/backup.sh nightly      # writes a timestamped dump under backups/
```

## Tests

```bash
python -m pytest               # unit tests; integration tests skip by default
ARGUS_TEST_RESET=1 python -m pytest   # also run integration tests (RESEEDS demo workspaces)
```

Integration tests reseed the `cressida`/`valkyrie` demo workspaces, so they
require an explicit opt-in and never globally wipe the database.

## Roadmap

- Learned layer over the graph (node2vec / GNN / spreading-activation) for
  associative recall, on top of the explainable weighted graph.
- Vector embeddings for RAG (currently Neo4j full-text keyword search).
- Voice input (speech-to-text) feeding `router.handle`.
- Cameras / vision, mapping physical garage zones to contexts (and feeding
  lower-confidence observations into the graph, same staging path as enrichment).
