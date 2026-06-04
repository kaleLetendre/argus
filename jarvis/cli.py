"""A text REPL that simulates talking to Jarvis.

Run with ``python -m jarvis``. Type what you would say:

    > open project cressida
    > what's the torque spec on the cam caps
    > where am i

Type ``list`` to see contexts, ``help`` for commands, ``quit`` to exit.
"""

from __future__ import annotations

import sys
from pathlib import Path

from jarvis.router import handle
from jarvis.workspace import Session, WorkspaceRegistry

# Default workspaces root is ``<repo>/workspaces``.
DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "workspaces"


def _print_list(registry: WorkspaceRegistry) -> None:
    workspaces = registry.all()
    if not workspaces:
        print("  (no workspaces found)")
        return
    for ws in workspaces:
        aliases = f"  [{', '.join(ws.aliases)}]" if ws.aliases else ""
        print(f"  {ws.name}{aliases}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = Path(argv[0]) if argv else DEFAULT_ROOT

    registry = WorkspaceRegistry(root)
    session = Session()
    registry.discover()

    print(f"Jarvis workspace shell — root: {root}")
    print("Type 'help' for commands, 'quit' to exit.\n")

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
            _print_list(registry)
            continue

        reply = handle(line, registry, session)
        print(f"  {reply.text}")


if __name__ == "__main__":
    raise SystemExit(main())
