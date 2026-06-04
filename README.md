# Jarvis

A voice-navigable, context-aware assistant for the garage. You speak a command
to move Jarvis into a **context** ("jarvis, open project cressida"), then ask
questions answered from that context's knowledge ("what's the torque spec on the
cam caps for my current engine").

This repo currently implements the **workspace system**: the core that holds
contexts, tracks which one is active and what it's focused on, and answers
questions. Voice (microphones) and vision (cameras) are future layers that feed
into this same core.

## Concepts

- **Workspace / context** — one project, stored as a folder under `workspaces/`.
- **Entity graph** (`graph.yaml`) — the nodes (engine, parts, tools) with
  structured **facts** (`cam_cap_torque: 18 ft-lb`) and **edges** between them.
- **Docs** (`docs/*.md`) — free-form prose knowledge, searched by RAG.
- **Hybrid retrieval** — a question checks structured facts first (exact), then
  falls back to RAG over the docs.
- **Focus** — "my current engine" is *inferred from conversation*: the most
  recently mentioned engine, or the only one in the project.

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m jarvis            # text shell that simulates the voice flow
```

Then type what you'd say:

```
> open project cressida
> what's the torque spec on the cam caps
> what's the firing order on my current engine
> how do I set the cam timing
```

## Adding a context

Create `workspaces/<slug>/` with a `workspace.yaml` (name + aliases),
a `graph.yaml` (entities/facts/edges), and any `docs/*.md`. See
`workspaces/cressida/` for the reference example.

## Tests

```bash
python -m pytest
```
