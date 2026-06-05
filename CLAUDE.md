# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Argus is a voice-navigable, context-aware assistant for a garage. The end goal:
microphones (and later cameras) let the user speak a command to move Argus into
a **context** ("argus, open project cressida"), then ask questions answered from
that context's knowledge ("torque spec on the cam caps for my current engine").

Built so far is the **workspace system** (the foundation). Voice/STT and vision
are deliberately *not* built yet; they are future input layers that will feed
text into the same `router.handle` entry point.

## Commands

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt        # PyYAML + neo4j driver; pytest for tests
scripts/setup-neo4j.sh                 # start Neo4j (Docker) + seed the graph
python -m argus                        # text shell simulating the voice flow
python -m argus.store.importer --reset # re-seed the graph from the YAML
python -m argus.enrich run <slug>      # Claude studies a project's docs, stages proposals
python -m argus.enrich review <slug>   # review staged proposals (with evidence)
python -m argus.enrich approve <pid>   # apply a proposal;  reject <pid> to discard
python -m pytest                       # unit tests only (integration tests skip)
ARGUS_TEST_RESET=1 python -m pytest    # +integration; RESEEDS the demo workspaces
python -m pytest tests/test_workspace.py::test_structured_fact_answer  # one test
docker compose up -d / down            # start / stop Neo4j
scripts/backup.sh [label]              # back up the graph (DB is source of truth)
```

Neo4j runs in Docker (`docker-compose.yml`), bound to `127.0.0.1` only. The
browser is at http://localhost:7474 (user `neo4j`, password in `.env`). The
driver connects over Bolt at `bolt://localhost:7687`. Integration tests **skip**
automatically if Neo4j is unreachable.

## Architecture

Data flows: **utterance → router → (navigate | answer) → reply**. Everything
downstream of the router is text, so it doesn't care whether words were typed or
will later arrive from speech-to-text.

**Neo4j is the canonical store.** The YAML under `workspaces/` is a *seed/import*
format, not the runtime source. At runtime everything queries Neo4j.

- `argus/store/` — the knowledge network (Neo4j).
  - `neo4j_store.py` — `Neo4jStore`: owns the schema (constraints + Lucene
    full-text indexes), import, and all graph queries. Graph model:
    `(:Workspace)`, `(:Entity)` + a typed label (`:Engine`, `:Part`) for browser
    colour, `(:Entity)-[:HAS_FACT]->(:Fact {value,unit,note,source,confidence})`,
    edges `(:Entity)-[:<RELATION> {weight,confidence}]->(:Entity)`, and `(:Doc)`.
    `uid = "<slug>:<id>"` because Community edition is single-database, so
    workspaces are partitioned by node, not by database.
  - `importer.py` — loads the YAML workspaces into Neo4j (`--reset` wipes first).
- `argus/workspace/` — the in-memory model + seed loader.
  - `models.py` — `Workspace`, `Graph`, `Entity`, `Edge`, `Fact` dataclasses.
    `Edge` carries `weight`+`confidence`; `Fact` carries `confidence`. Fuzzy
    name/fact scoring (stdlib `difflib`) lives here and is reused to re-rank
    Neo4j full-text candidates.
  - `loader.py` — reads a project folder (`workspace.yaml` + `graph.yaml` +
    `docs/*.md`) into a `Workspace` for the importer.
  - `session.py` — per-conversation state: the **active** workspace and the
    **inferred focus**. Focus is *not* set by command; `infer_focus(type, store)`
    resolves "my current engine" from a mention history (most-recent-first),
    falling back to the unique entity of that type via the store.
  - `registry.py` — legacy file-based discovery; superseded by the store at
    runtime, kept only as a reference. Don't wire it back into the runtime path.
- `argus/knowledge/query.py` — `answer_question(question, store, session)`, the
  hybrid lookup. **Fact-first**: resolve the entity (entity full-text index, or
  inferred focus), check its facts, else scan workspace facts (fact full-text
  index); only then fall back to RAG (`store.search_docs`, doc full-text index).
  Returns an `Answer` with provenance; surfaces fact `confidence` when < 1.0.
- `argus/enrich/` — Claude ruminates over a project's docs to grow its graph.
  - `llm.py` — one-shot call to Claude via the **Claude Agent SDK**
    (`claude-agent-sdk`), driving the local logged-in `claude` CLI. **Hard rule:
    subscription only, never API credits** — it strips
    `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` from the SDK subprocess env so it
    can only use the subscription session (fails rather than billing if the CLI
    isn't logged in). Locked to pure reasoning: no tools, `setting_sources=[]`
    (so it ignores this repo's CLAUDE.md), one turn.
  - `extractor.py` — builds the prompt (existing graph snapshot + docs), parses
    Claude's JSON proposals, caps machine `confidence` at 0.9. `enrich_workspace`
    takes an injectable `llm` so the pipeline is tested without spending credits.
  - Proposals are **staged, never auto-applied**: stored as `(:Proposal)` nodes
    (status pending/approved/rejected) with the supporting doc quote. Approval
    materialises them into the graph tagged `source: "claude-extraction:<doc>"`.
- `argus/router.py` — classifies an utterance as navigation, status, **study**
  ("study the docs" triggers enrichment), or a question. The seam the voice
  front end will call.
- `argus/config.py` — reads `.env` (Neo4j URI/user/password); `argus/cli.py` — REPL.

## Key design decisions (agreed with the user, do not silently change)

- **Neo4j is the source of truth**, with backups (`scripts/backup.sh`), not
  YAML-as-source. The YAML is seed/import only. Once voice/vision write knowledge
  automatically, hand-editing YAML stops; edits happen in the graph.
- **Contexts are an entity graph.** Entities are nodes; **facts are their own
  `(:Fact)` nodes** (chosen over flat properties) so provenance is first-class,
  queryable, visible in the browser, and linkable to source docs later.
- **Relationships are weighted.** Edges carry `weight` (association strength) and
  `confidence`; facts carry `confidence`. This is the explainable, symbolic core.
  A learned "neural"/embedding layer (node2vec / GNN / spreading-activation) is a
  planned *separate layer over* the graph, not a rebuild of it. Do not turn the
  symbolic graph into a black box; explainable provenance is the point.
- **Hybrid retrieval, fact-first then RAG.** Structured specs answer exactly;
  docs are the fallback.
- **Each project is its own graph (logical isolation on Community).** One Neo4j
  DB, but every node carries `workspace` and every query is scoped to it; no edge
  crosses projects (`neighbors` filters `n.workspace`). Physical per-database
  isolation would need Enterprise; we chose logical. Keep all new queries scoped.
- **LLM enrichment is staged, never auto-applied**, and always tagged
  `claude-extraction` with a capped confidence. A wrong torque spec is dangerous,
  so machine-inferred knowledge is reviewed and stays distinguishable from stated
  facts. Don't change this to auto-apply without the user.
- **Never spend Anthropic API credits (hard rule).** All Claude calls go through
  the user's subscription via the logged-in `claude` CLI. `enrich/llm.py` strips
  `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` before every call to guarantee this.
  Do not add an API-key fallback or a dual-mode toggle, and never put a key in
  `.env`. The cost cap is the subscription; API credits would be uncapped spend.
- **Focus is inferred from conversation**, never set by an explicit command.
- **No silently-chosen voice or embedding stack.** STT and the RAG embedding
  backend are still open. Doc search is currently Neo4j's Lucene full-text
  (keyword), a placeholder for vector search. Do not commit to an embedding model
  or STT engine without asking the user.

## Conventions

- Keep the seed YAML human-editable; facts are a scalar or a
  `{value, unit, note, source, confidence}` mapping (`Fact.parse` handles both).
  Preserve `source`/`note`/`confidence` so answers can cite and qualify a spec.
- Schema/index changes go through `Neo4jStore.setup_schema` (idempotent,
  `IF NOT EXISTS`). After changing the model, re-run the importer with `--reset`.
- **Integration tests reseed the demo workspaces and require opt-in**
  (`ARGUS_TEST_RESET=1`, or `NEO4J_TEST_URI` for a throwaway instance); they use
  scoped `clear_workspace`, never a global wipe. Never point them at a graph
  holding real knowledge without expecting cressida/valkyrie to be reseeded.
- Multi-statement writes (import, approve) run in `execute_write` transactions.
  Approving a proposal is conflict-checked: it refuses to overwrite a stated
  fact that's at least as confident. Re-running enrichment dedupes on a content
  signature, so proposals don't pile up.
- Secrets live in `.env` (gitignored). Never commit `.env` or `data/`.
- When adding a context, give it generous `aliases` in `workspace.yaml` and on
  entities (that's what makes spoken navigation and focus matching forgiving).
