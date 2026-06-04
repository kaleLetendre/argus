"""A text REPL that simulates talking to Argus.

Run with ``python -m argus``. Type what you would say:

    > open project cressida
    > what's the torque spec on the cam caps
    > where am i

Type ``list`` to see contexts, ``help`` for commands, ``quit`` to exit.

Talks to the canonical Neo4j store. If the graph is empty, seed it first with
``python -m argus.store.importer``.
"""

from __future__ import annotations

import sys

from argus.config import neo4j_config
from argus.router import handle
from argus.store import Neo4jStore
from argus.workspace import Session


def _print_list(store: Neo4jStore) -> None:
    workspaces = store.list_workspaces()
    if not workspaces:
        print("  (no workspaces in the store; run: python -m argus.store.importer)")
        return
    for ws in workspaces:
        aliases = f"  [{', '.join(ws.aliases)}]" if ws.aliases else ""
        print(f"  {ws.name}{aliases}")


def main(argv: list[str] | None = None) -> int:
    config = neo4j_config()
    store = Neo4jStore(config)
    try:
        store.verify()
    except Exception as exc:  # noqa: BLE001
        print(f"Cannot reach Neo4j at {config.uri}: {exc}", file=sys.stderr)
        print("Start it with: docker compose up -d", file=sys.stderr)
        return 1

    session = Session()
    print(f"Argus — knowledge store: {config.uri}")
    if not store.list_workspaces():
        print("No contexts loaded yet. Seed with: python -m argus.store.importer")
    print("Type 'help' for commands, 'quit' to exit.\n")

    try:
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0

            if not line:
                continue
            if line in {"quit", "exit"}:
                return 0
            if line == "help":
                print("  open project <name>   switch context")
                print("  <question>            ask within the active context")
                print("  where am i            show active context")
                print("  list                  list known contexts")
                print("  quit                  exit")
                continue
            if line == "list":
                _print_list(store)
                continue

            reply = handle(line, store, session)
            print(f"  {reply.text}")
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
