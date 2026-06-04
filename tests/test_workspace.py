"""Tests for Argus.

Two layers:
* pure unit tests on the YAML loader / model (no database needed), and
* integration tests against a live Neo4j store (skipped if it's unreachable).
"""

from pathlib import Path

import pytest

from argus.config import WORKSPACES_ROOT, neo4j_config
from argus.knowledge import answer_question
from argus.router import handle
from argus.store import Neo4jStore
from argus.store.importer import import_all
from argus.workspace import Session, load_workspace


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
    s = Neo4jStore(neo4j_config())
    try:
        s.verify()
    except Exception:  # noqa: BLE001
        pytest.skip("Neo4j not reachable; skipping integration tests")
    import_all(s, reset=True)
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
