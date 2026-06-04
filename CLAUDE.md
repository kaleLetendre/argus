# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Jarvis is a voice-navigable, context-aware assistant for a garage. The end goal:
microphones (and later cameras) let the user speak a command to move Jarvis into
a **context** ("jarvis, open project cressida"), then ask questions answered from
that context's knowledge ("torque spec on the cam caps for my current engine").

Built so far is the **workspace system** (the foundation). Voice/STT and vision
are deliberately *not* built yet; they are future input layers that will feed
text into the same `router.handle` entry point.

## Commands

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt        # only dep is PyYAML; pytest for tests
python -m jarvis                        # text shell simulating the voice flow
python -m pytest                        # run all tests
python -m pytest tests/test_workspace.py::test_structured_fact_answer  # single test
```

The `python -m jarvis` shell is the primary way to manually exercise the system:
type utterances as if spoken (`open project cressida`, then a question).

## Architecture

Data flows: **utterance → router → (navigate | answer) → reply**. Everything
downstream of the router is text, so it doesn't care whether words were typed or
will later arrive from speech-to-text.

- `jarvis/workspace/` — the context model and state.
  - `models.py` — `Workspace`, `Graph`, `Entity`, `Edge`, `Fact`. Entities carry
    structured facts; edges are relationships. Fuzzy name/fact matching lives
    here (stdlib `difflib`, intentionally no fuzzy-match dependency).
  - `loader.py` — reads one project folder (`workspace.yaml` + `graph.yaml` +
    `docs/*.md`) into a `Workspace`.
  - `registry.py` — discovers all workspaces under the root and fuzzy-resolves a
    spoken name ("project cressida") to one. This is what makes navigation work.
  - `session.py` — per-conversation state: the **active** workspace and the
    **inferred focus**. Focus is *not* set by command; `infer_focus(type)`
    resolves "my current engine" from a mention history (most-recent-first),
    falling back to the unique entity of that type.
- `jarvis/knowledge/` — answering questions within the active context.
  - `query.py` — `answer_question`, the hybrid lookup. **Fact-first**: resolve
    the target entity (named directly, or inferred focus), check its structured
    facts, and if none matches, scan all entities' facts; only then fall back to
    RAG. Returns an `Answer` carrying provenance.
  - `rag.py` — **placeholder retrieval**. Scores doc paragraphs by keyword
    overlap so the flow works without an embedding stack. The `retrieve()`
    signature is the contract; swapping in real embeddings is a drop-in change.
- `jarvis/router.py` — classifies an utterance as navigation, status, or a
  question. The single seam the future voice front end will call.
- `jarvis/cli.py` — the REPL.
- `workspaces/` — the data. Each subfolder is one context. `cressida/` is the
  reference example; mirror its structure when adding contexts.

## Key design decisions (agreed with the user, do not silently change)

- **Contexts are an entity graph**, not flat or a deep tree. A context is a
  project folder; the graph (`graph.yaml`) is a project file holding nodes +
  facts + edges. Prose lives separately in `docs/*.md`.
- **Hybrid retrieval, fact-first then RAG.** Structured specs must answer
  exactly; docs are the fallback.
- **Focus is inferred from conversation**, never set by an explicit command.
- **No silently-chosen voice or embedding stack.** STT and the RAG embedding
  backend are open decisions; `rag.py` is a flagged keyword stub. Do not commit
  to an embedding model or STT engine without asking the user.

## Conventions

- Plain dataclasses + dicts over the YAML so the whole graph stays inspectable
  and greppable on disk. Keep new on-disk formats human-editable YAML/markdown.
- Entity `facts` are stored as a scalar or a `{value, unit, note, source}`
  mapping; `Fact.parse` handles both. Preserve `source`/`note` so answers can
  cite where a spec came from.
- When adding a context, give it generous `aliases` in `workspace.yaml` (that's
  what makes spoken navigation forgiving) and on entities (for focus matching).
