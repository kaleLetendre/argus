# Pattern: agent -> system contracts via MCP

> Status: **adopted** (D27 in [../architecture.md](../architecture.md)), scoped to
> agent -> system request/response edges. This doc is the rationale and the scope; the
> first concrete manifest is [../memory/graph/mcp.md](../memory/graph/mcp.md).

## The pattern

For the edges where **agents calls another system** (today agents -> memory; later
agents -> tools / sensors / actuators), define the contract the way **MCP** defines
tools and resources: a tool has a name, a description, a JSON-Schema input, and a
structured output. Treat **agents as an MCP host** and **each system it calls as an
MCP server**.

## Why

The agent is an LLM, and current models are heavily trained on the MCP / tool-use
calling convention. If memory's operations are presented to the agent as MCP tools,
the agent calls them through its **native tool-use path** (the thing it is best at)
instead of us hand-rolling a bespoke "here is how to format a memory query" prompt
scaffold. We spend the model's training instead of fighting it.

## The constraint: MCP earns its keep on one plane only

MCP pays off only when **both** hold: the **LLM is the caller**, and the interaction is
**request/response**. If either is false, MCP is either pointless (JSON-RPC overhead
for no training benefit) or a mismatch. That scopes it precisely.

**Use MCP** (LLM-as-caller, request/response):
- **agent -> memory** (recall, apply, search): agent is the caller, memory the
  capability. memory becomes an MCP server; agents is the host.
- **agent -> future tools / actuators** (on-demand query or command): same shape.
  Generalizes: *agents is an MCP host, every system it calls on demand is an MCP server
  exposing tools.* "Add a system" becomes "stand up a server and let the agent discover
  its tools."

**Do not use MCP:**
- **interaction -> agents** (an utterance arrives): the caller is not the LLM. Front
  door, its own contract.
- **agents -> interaction `push`** (proactive outbound, D40): the caller is the LLM and
  it is request-shaped, but it is the **front door's reverse direction**: it rides the
  interaction<->agents contract and transport, not a separate MCP server on interaction
  (D56e). The front door is one bidirectional contract.
- **memory -> agents** (study asks the agent to reason): caller is not the LLM, and
  it is async. A **job on the queue**, not a tool call.
- **background task delivery to agent workers** (async, fire-and-forget, pooled): the
  **queue**, not request/response.
- **sensor -> memory ingestion / live feeds** (no LLM, continuous): a **stream/write
  path**. MCP is request/response JSON-RPC, not a data bus.

**Nuance: the line is query vs stream, not sensor-vs-not.** A sensors system can expose
an MCP query tool (`get_current_temperature`) the agent calls on demand; what is not
MCP is its continuous ingestion firehose. Same system, two edges.

**The planes that fall out:**
- **MCP plane** (this doc): the agent's outbound, on-demand capability calls.
- **Queue plane**: async jobs (background tasks, reason/study requests).
- **Stream/ingest plane**: continuous data with no LLM (sensor ingest, live feeds).
- **Front door**: interaction -> agents.

Side effect: this naturally splits the current `agents <-> memory` contract's two
directions. The agent->memory direction becomes an MCP tool/resource manifest; the
memory->agent reason request moves to the queue plane.

## Mapping our IRs onto MCP concepts

- Operations (`recall`, `remember`, `search`, `neighbors`, `activate`, `set_importance`,
  `track_event`, `revise_question`, `note_surfaced`) -> **tools**, with `QuerySpec` /
  `Assertion` as the tool `inputSchema`.
- `RankedFact` / `ApplyResult` -> **structured output** schemas.
- Browsable read-only data (`snapshot`, the `entity`/`source` views, the live graph view) ->
  **resources** (addressable data, not actions), which fits better than tools.

## How it fits decisions we already made

MCP already solves three things we would otherwise invent, each rhyming with an
existing decision:

- **Transport / placement (D18, D23):** MCP servers run over stdio locally or
  HTTP/SSE remotely, chosen by config. That *is* "same machine or different machine,
  by configuration."
- **Extensibility (D26):** `tools/list` discovery is exactly "a new system advertises
  its contract and the agent picks it up," no rewiring.
- **Configured connection (D25):** an MCP server is just another configured connection
  the agent attaches to, same mental model as the model connection.

So we adopt a wire format the model already speaks and inherit clients, schemas,
transport, and discovery instead of inventing our own.

## Keep straight

- **memory's internals stay private.** The tool manifest is the adapter on memory's
  contract boundary, not memory's guts. memory can still be a graph, SQL, or RAG
  behind those tools, so swappability is preserved.

## Resolved: adopt MCP for real (at build); design as a tool manifest now

Decided (D27). Design the agent -> system contracts as tool/resource manifests now;
wire them as real MCP / native tool-use at build time. The training payoff only lands
when the agent actually sees these as tools at runtime, so "for real" is the target;
writing the design that way today costs nothing and decides transport at build.
**This constrains D25:** the agent's model connection must be **tool-capable** (most
capable models are; a bare local model may not be).

## Where it lives now

The first agent -> system manifest is the agents -> memory contract:
[../memory/graph/mcp.md](../memory/graph/mcp.md) (recall/remember/search/neighbors as tools;
snapshot/entity/source as resources). The reverse direction (memory -> agents reasoning) moved
to the **queue plane** and is documented with the Task model in
[../runtime-topology.md](../runtime-topology.md). Future agent -> tool / actuator
systems follow this same shape: each an MCP server the agent discovers and calls.
