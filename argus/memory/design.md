# Compartment: memory

> Status: draft. memory is not one store; it is a set of **typed memory systems**, each
> its own MCP server. See [system_goal.txt](system_goal.txt) for the role.

## What memory is

memory's job (store and recall what is known) can be filled by different
implementations. Rather than hide them behind one universal interface, **each memory
type is its own MCP server with its own tools, as a subdirectory here** (D29):

- [graph/](graph/) — the self-tuning Hebbian knowledge graph, the type we are
  researching first. Tools: `recall`, `remember`, `search`, `neighbors`, `activate`,
  `set_importance`, `track_event`, `revise_question`, `note_surfaced`.
  See [graph/design.md](graph/design.md), [graph/memory-model.md](graph/memory-model.md),
  [graph/mcp.md](graph/mcp.md).
- (later) `sql/`, `rag/`, ... each a different MCP server with its own tools.

**Hot-swap = configure the agent to a different memory MCP.** Because each type is its
own MCP server and not a shared abstraction, a SQL or RAG memory can expose whatever
tools fit it; nothing has to pretend to be a graph. This is what makes "memory is
swappable" real, and it lets us compare types while researching whether the graph
memory is even viable.

## Boundaries (true of every type)

- memory holds knowledge; the other systems borrow from it (they keep no copy).
- memory does not talk to the user and does not reason. When thinking is needed that is
  a job for agents (on the queue plane), not memory.
- A type's internals stay private behind its MCP manifest.
