"""Seed Neo4j from the on-disk YAML workspaces.

The YAML under ``workspaces/`` is the *seed/import* format. Neo4j is the
canonical store at runtime; this loads (or re-loads) the seed into it. Run via::

    python -m argus.store.importer            # import all workspaces
    python -m argus.store.importer --reset    # wipe graph first, then import
"""

from __future__ import annotations

import argparse
import sys

from argus.config import WORKSPACES_ROOT, neo4j_config
from argus.store.neo4j_store import Neo4jStore
from argus.workspace.loader import load_workspace


def import_all(store: Neo4jStore, reset: bool = False) -> list[str]:
    store.setup_schema()
    if reset:
        store.clear()
        store.setup_schema()
    imported: list[str] = []
    for child in sorted(WORKSPACES_ROOT.iterdir()):
        if child.is_dir() and (child / "workspace.yaml").is_file():
            ws = load_workspace(child)
            store.import_workspace(ws)
            imported.append(ws.name)
    return imported


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import YAML workspaces into Neo4j.")
    parser.add_argument("--reset", action="store_true", help="wipe the graph before importing")
    args = parser.parse_args(argv)

    with Neo4jStore(neo4j_config()) as store:
        try:
            store.verify()
        except Exception as exc:  # noqa: BLE001
            print(f"Cannot reach Neo4j: {exc}", file=sys.stderr)
            print("Is the container up? Try: docker compose up -d", file=sys.stderr)
            return 1
        names = import_all(store, reset=args.reset)
    print(f"Imported {len(names)} workspace(s): {', '.join(names) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
