"""Tests for Argus.

Two layers:
* pure unit tests on the YAML loader / model (no database needed), and
* integration tests against a live Neo4j store (skipped if it's unreachable).
"""

import os
from pathlib import Path

import pytest

from argus.config import WORKSPACES_ROOT, Neo4jConfig, neo4j_config
from argus.knowledge import answer_question
from argus.router import handle
from argus.store import Neo4jStore
from argus.workspace import Session, load_workspace

# Only the demo workspaces are ever touched by tests.
SEED_SLUGS = ("cressida", "valkyrie")


# --------------------------------------------------------------------------
# Unit tests: loader + model (no Neo4j)
# --------------------------------------------------------------------------
def test_loader_parses_weights_and_confidence():
    ws = load_workspace(WORKSPACES_ROOT / "cressida")
    turbo = ws.graph.entities["turbo"]
    assert turbo.facts["target_boost"].confidence == 0.6
    edge = next(e for e in ws.graph.edges if e.source == "turbo")
    assert edge.weight == 0.9 and edge.confidence == 0.8


def test_entity_fact_matching_is_fuzzy():
    ws = load_workspace(WORKSPACES_ROOT / "cressida")
    engine = ws.graph.entities["engine-2jz"]
    assert engine.find_fact("torque on the cam caps").key == "cam_cap_torque"


# --------------------------------------------------------------------------
# Integration tests: live Neo4j store
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def store():
    # Guard: these tests RESEED the demo workspaces, so they must not run against
    # a real graph by accident. Opt in with ARGUS_TEST_RESET=1, or point them at a
    # throwaway instance with NEO4J_TEST_URI. They never globally wipe the DB and
    # only touch the SEED_SLUGS subgraphs.
    test_uri = os.environ.get("NEO4J_TEST_URI")
    if not test_uri and not os.environ.get("ARGUS_TEST_RESET"):
        pytest.skip("integration tests reseed demo workspaces; "
                    "set ARGUS_TEST_RESET=1 (or NEO4J_TEST_URI) to run")
    cfg = neo4j_config()
    if test_uri:
        cfg = Neo4jConfig(uri=test_uri, user=cfg.user, password=cfg.password)
    s = Neo4jStore(cfg)
    try:
        s.verify()
    except Exception:  # noqa: BLE001
        pytest.skip("Neo4j not reachable; skipping integration tests")
    s.setup_schema()
    for slug in SEED_SLUGS:
        s.clear_workspace(slug)          # scoped, never `MATCH (n) DETACH DELETE n`
        s.import_workspace(load_workspace(WORKSPACES_ROOT / slug))
    yield s
    s.close()


def test_registry_resolves_spoken_name(store):
    assert store.resolve_workspace("project cressida").slug == "cressida"
    assert store.resolve_workspace("cressida swap").slug == "cressida"
    assert store.resolve_workspace("totally unknown thing") is None


def test_navigation(store):
    session = Session()
    nav = handle("argus, open project cressida", store, session)
    assert nav.kind == "nav"
    assert session.active.slug == "cressida"


def test_structured_fact_answer(store):
    session = Session()
    handle("open project cressida", store, session)
    reply = handle("what's the torque spec on the cam caps", store, session)
    assert "18 ft-lb" in reply.text


def test_inferred_focus_for_current_engine(store):
    ws = store.resolve_workspace("cressida")
    session = Session()
    session.activate(ws)
    answer = answer_question("what is the firing order on my current engine", store, session)
    assert "1-5-3-6-2-4" in answer.text


def test_low_confidence_is_surfaced(store):
    session = Session()
    handle("open project cressida", store, session)
    reply = handle("what's the target boost on the turbo", store, session)
    assert "18 psi" in reply.text
    assert "confidence" in reply.text.lower()


def test_rag_fallback_for_prose(store):
    session = Session()
    handle("open project cressida", store, session)
    reply = handle("how do I set the cam timing", store, session)
    assert "tdc" in reply.text.lower()


def test_weighted_neighbors(store):
    rows = store.neighbors("cressida", "cressida:engine-2jz")
    turbo = next(r for r in rows if "Turbo" in r["name"])
    assert turbo["weight"] == 0.9


def test_question_without_context_is_rejected(store):
    session = Session()
    reply = handle("what's the boost target", store, session)
    assert reply.kind == "error"


# --------------------------------------------------------------------------
# Per-project isolation
# --------------------------------------------------------------------------
def test_current_engine_is_scoped_to_active_project(store):
    """'my current engine' must resolve within the active project only."""
    s1 = Session()
    s1.activate(store.resolve_workspace("valkyrie"))
    a1 = answer_question("firing order on my current engine", store, s1)
    assert "1-2-4-3" in a1.text  # CB750, not the 2JZ

    s2 = Session()
    s2.activate(store.resolve_workspace("cressida"))
    a2 = answer_question("firing order on my current engine", store, s2)
    assert "1-5-3-6-2-4" in a2.text


def test_no_cross_project_neighbors(store):
    rows = store.neighbors("valkyrie", "valkyrie:engine-cb750")
    names = [r["name"] for r in rows]
    assert "Keihin CV Carburetors" in names
    assert all("Turbo" not in n and "Gasket" not in n for n in names)  # no Cressida parts


# --------------------------------------------------------------------------
# Enrichment pipeline (fake LLM, no credits spent)
# --------------------------------------------------------------------------
_FAKE_JSON = """```json
{
  "entities": [
    {"id": "oil-filter", "type": "part", "name": "Oil Filter", "aliases": ["filter"],
     "evidence": "new oil filter", "doc": "build-log.md", "confidence": 0.8}
  ],
  "facts": [
    {"entity_id": "engine-2jz", "key": "oil_capacity", "value": 5.4, "unit": "L",
     "note": null, "evidence": "holds 5.4L", "doc": "build-log.md", "confidence": 0.7}
  ],
  "relationships": [
    {"source": "oil-filter", "relation": "installed_on", "target": "engine-2jz",
     "weight": 1.0, "confidence": 0.8, "evidence": "filter on the engine", "doc": "build-log.md"}
  ]
}
```"""


def test_enrichment_stage_review_approve(store):
    from argus.enrich.extractor import enrich_workspace

    fake_llm = lambda prompt, system, model: _FAKE_JSON  # noqa: E731
    result = enrich_workspace("cressida", store, llm=fake_llm)
    assert result["staged"] == 3

    pending = store.list_proposals("cressida")
    assert len(pending) >= 3

    # Nothing is in the graph until approved.
    session = Session()
    handle("open project cressida", store, session)
    before = handle("what's the oil capacity on my current engine", store, session)
    assert "5.4" not in before.text

    # Approve the fact; it becomes queryable, and surfaces as lower-confidence.
    fact_pid = next(p["pid"] for p in pending if p["kind"] == "fact")
    assert store.approve_proposal(fact_pid)["status"] == "applied"
    s2 = Session()
    handle("open project cressida", store, s2)
    after = handle("what's the oil capacity on my current engine", store, s2)
    assert "5.4" in after.text and "confidence" in after.text.lower()

    # Reject the entity proposal; it leaves the pending queue.
    entity_pid = next(p["pid"] for p in pending if p["kind"] == "entity")
    assert store.set_proposal_status(entity_pid, "rejected") is True
    still_pending = [p["pid"] for p in store.list_proposals("cressida")]
    assert entity_pid not in still_pending


def test_parse_proposals_handles_fenced_json():
    from argus.enrich.extractor import parse_proposals

    props = parse_proposals(_FAKE_JSON)
    kinds = sorted(p["kind"] for p in props)
    assert kinds == ["entity", "fact", "relationship"]
    # Machine confidence is capped below certainty.
    assert all(p["confidence"] <= 0.9 for p in props)


def test_parse_proposals_survives_garbage():
    from argus.enrich.extractor import parse_proposals

    assert parse_proposals("not json at all") == []
    assert parse_proposals("") == []
    assert parse_proposals("```json\n{ broken : ]\n```") == []


# --------------------------------------------------------------------------
# Regression tests for the design-review findings
# --------------------------------------------------------------------------
def test_search_facts_ranked_best_first(store):
    """The fact scan must return the BEST fuzzy match, not Lucene order."""
    ranked = store.search_facts("cressida", "head bolt torque")
    assert ranked, "expected at least one fact hit"
    top_entity, top_fact, top_score = ranked[0]
    assert top_fact.key == "head_bolt_torque"
    scores = [score for _, _, score in ranked]
    assert scores == sorted(scores, reverse=True)


def test_weak_fact_question_does_not_fabricate(store):
    """A question with no good fact match must not answer with a bogus spec.
    Checked via provenance: the answer must not come from a graph fact."""
    session = Session()
    session.activate(store.resolve_workspace("cressida"))
    ans = answer_question("what colour is the bellhousing", store, session)
    assert not ans.source.startswith("graph fact")


def test_enrichment_dedupes_on_rerun(store):
    """Re-running 'study' must not pile up duplicate pending proposals."""
    from argus.enrich.extractor import enrich_workspace

    fake = lambda prompt, system, model: _FAKE_JSON  # noqa: E731
    first = enrich_workspace("valkyrie", store, llm=fake)
    assert first["staged"] == 3
    second = enrich_workspace("valkyrie", store, llm=fake)
    assert second["staged"] == 0  # all duplicates, nothing new staged


def test_approve_refuses_to_overwrite_a_trusted_fact(store):
    """Approving a Claude fact that conflicts with a stated, higher-confidence
    fact must be refused, not silently clobbered."""
    from argus.enrich.extractor import enrich_workspace

    # Claude 'proposes' a different cam cap torque at lower confidence.
    conflicting = """```json
    {"facts": [{"entity_id": "engine-2jz", "key": "cam_cap_torque", "value": 99,
      "unit": "ft-lb", "evidence": "q", "doc": "build-log.md", "confidence": 0.7}]}
    ```"""
    enrich_workspace("cressida", store, llm=lambda p, s, m: conflicting)
    pid = next(p["pid"] for p in store.list_proposals("cressida")
               if "cam_cap_torque" in p["summary"])
    result = store.approve_proposal(pid)
    assert result["status"] == "conflict"
    # The trusted value is untouched.
    s2 = Session()
    handle("open project cressida", store, s2)
    assert "18 ft-lb" in handle("cam cap torque on my current engine", store, s2).text


def test_approved_new_entity_is_linked_into_its_workspace(store):
    """A fact proposal for a brand-new entity must link it via IN_WORKSPACE and
    must not create a stray duplicate Workspace node."""
    from argus.enrich.extractor import enrich_workspace

    payload = """```json
    {"facts": [{"entity_id": "oil-cooler", "key": "capacity", "value": 0.5,
      "unit": "L", "evidence": "q", "doc": "build-log.md", "confidence": 0.6}]}
    ```"""
    enrich_workspace("cressida", store, llm=lambda p, s, m: payload)
    pid = next(p["pid"] for p in store.list_proposals("cressida")
               if "oil-cooler" in p["summary"])
    assert store.approve_proposal(pid)["status"] == "applied"

    with store._driver.session() as sess:  # noqa: SLF001 - white-box check
        linked = sess.run(
            "MATCH (e:Entity {uid:'cressida:oil-cooler'})-[:IN_WORKSPACE]->"
            "(w:Workspace {slug:'cressida'}) RETURN count(w) AS n"
        ).single()["n"]
        ws_count = sess.run(
            "MATCH (w:Workspace {slug:'cressida'}) RETURN count(w) AS n"
        ).single()["n"]
    assert linked == 1
    assert ws_count == 1  # no stray duplicate workspace


def test_entity_types_is_data_driven(store):
    assert set(store.entity_types("valkyrie")) >= {"engine", "part"}
