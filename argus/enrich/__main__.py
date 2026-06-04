"""CLI for the rumination / review loop.

    python -m argus.enrich run cressida          # Claude studies the docs, stages proposals
    python -m argus.enrich review cressida        # list pending proposals with evidence
    python -m argus.enrich approve <pid>          # apply one proposal to the graph
    python -m argus.enrich reject <pid>           # discard one proposal
"""

from __future__ import annotations

import argparse
import sys

from argus.config import neo4j_config
from argus.enrich.extractor import enrich_workspace
from argus.store import Neo4jStore


def _run(store: Neo4jStore, slug: str, model: str) -> int:
    print(f"Studying the docs in '{slug}' with {model} (this calls Claude, may take a moment)...")
    result = enrich_workspace(slug, store, model=model)
    if result["staged"] == 0:
        print(f"Nothing staged ({result.get('reason', 'no new knowledge found')}).")
        return 0
    print(f"Staged {result['staged']} proposal(s) for review:")
    for p in result["proposals"]:
        print(f"  [{p['kind']}] {p.get('doc','')}  conf={p['confidence']:.0%}")
    print(f"\nReview them with:  python -m argus.enrich review {slug}")
    return 0


def _review(store: Neo4jStore, slug: str) -> int:
    pending = store.list_proposals(slug)
    if not pending:
        print("No pending proposals.")
        return 0
    for p in pending:
        print(f"\n  pid {p['pid']}  [{p['kind']}]  confidence {p['confidence']:.0%}  ({p['doc']})")
        print(f"    {p['summary']}")
        if p["evidence"]:
            print(f"    evidence: \"{p['evidence']}\"")
    print(f"\nApprove:  python -m argus.enrich approve <pid>")
    print(f"Reject:   python -m argus.enrich reject <pid>")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ruminate over docs and review proposals.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="study a workspace's docs and stage proposals")
    p_run.add_argument("slug")
    p_run.add_argument("--model", default="opus")
    p_rev = sub.add_parser("review", help="list pending proposals")
    p_rev.add_argument("slug")
    p_app = sub.add_parser("approve", help="apply a proposal to the graph")
    p_app.add_argument("pid")
    p_rej = sub.add_parser("reject", help="discard a proposal")
    p_rej.add_argument("pid")
    args = parser.parse_args(argv)

    with Neo4jStore(neo4j_config()) as store:
        try:
            store.verify()
        except Exception as exc:  # noqa: BLE001
            print(f"Cannot reach Neo4j: {exc}", file=sys.stderr)
            return 1

        if args.cmd == "run":
            return _run(store, args.slug, args.model)
        if args.cmd == "review":
            return _review(store, args.slug)
        if args.cmd == "approve":
            ok = store.approve_proposal(args.pid)
            print("Applied to the graph." if ok else "No such pending proposal.")
            return 0 if ok else 1
        if args.cmd == "reject":
            ok = store.set_proposal_status(args.pid, "rejected")
            print("Rejected." if ok else "No such proposal.")
            return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
