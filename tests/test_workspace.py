"""End-to-end checks for the workspace system against the example Cressida data."""

from pathlib import Path

import pytest

from argus.knowledge import answer_question
from argus.router import handle
from argus.workspace import Session, WorkspaceRegistry, load_workspace

ROOT = Path(__file__).resolve().parent.parent / "workspaces"


@pytest.fixture
def registry() -> WorkspaceRegistry:
    reg = WorkspaceRegistry(ROOT)
    reg.discover()
    return reg


def test_workspace_loads_graph_and_docs():
    ws = load_workspace(ROOT / "cressida")
    assert ws.slug == "cressida"
    assert "engine-2jz" in ws.graph.entities
    assert any(p.name == "cam-timing.md" for p in ws.doc_paths)


def test_registry_resolves_spoken_name(registry):
    assert registry.resolve("project cressida").slug == "cressida"
    assert registry.resolve("cressida swap").slug == "cressida"
    assert registry.resolve("totally unknown thing") is None


def test_navigation_then_status(registry):
    session = Session()
    nav = handle("argus, open project cressida", registry, session)
    assert nav.kind == "nav"
    assert session.active.slug == "cressida"


def test_structured_fact_answer(registry):
    session = Session()
    handle("open project cressida", registry, session)
    reply = handle("what's the torque spec on the cam caps", registry, session)
    assert "18 ft-lb" in reply.text


def test_inferred_focus_for_current_engine(registry):
    """'my current engine' should resolve to the single engine entity."""
    ws = registry.get("cressida")
    session = Session()
    session.activate(ws)
    answer = answer_question("what is the firing order on my current engine", ws, session)
    assert "1-5-3-6-2-4" in answer.text


def test_rag_fallback_for_prose(registry):
    session = Session()
    handle("open project cressida", registry, session)
    reply = handle("how do I set the cam timing", registry, session)
    assert "TDC" in reply.text or "tdc" in reply.text.lower()


def test_question_without_context_is_rejected(registry):
    session = Session()
    reply = handle("what's the boost target", registry, session)
    assert reply.kind == "error"
