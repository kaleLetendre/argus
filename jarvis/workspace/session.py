"""Conversation session state: which context is active and what it's focused on.

Two pieces of state move as you talk to Jarvis:

* the **active workspace** (set explicitly by "open project cressida"), and
* the **focused entity**, which is *inferred from conversation* rather than set
  by command. As entities get mentioned they're pushed onto a short history;
  "my current engine" then resolves to the most recently referenced engine, or,
  if none has come up yet, to the only engine in the project.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.workspace.models import Entity, Workspace


@dataclass
class FocusResult:
    """Outcome of trying to infer "my current <type>"."""

    entity: Entity | None
    ambiguous: list[Entity] = field(default_factory=list)
    reason: str = ""


class Session:
    """Mutable per-conversation state layered over the static workspaces."""

    def __init__(self) -> None:
        self.active: Workspace | None = None
        # Most-recent-first list of entity ids mentioned this conversation.
        self._mentions: list[str] = []

    # -- navigation ---------------------------------------------------------
    def activate(self, workspace: Workspace) -> None:
        """Switch context. Focus history does not carry across projects."""
        self.active = workspace
        self._mentions.clear()

    # -- focus tracking -----------------------------------------------------
    def note_mention(self, entity: Entity) -> None:
        """Record that an entity just came up, so focus can be inferred later."""
        self._mentions = [entity.id] + [m for m in self._mentions if m != entity.id]

    def infer_focus(self, entity_type: str) -> FocusResult:
        """Resolve "my current <entity_type>" from conversation so far.

        Order of preference: most recently mentioned entity of that type, then
        the unique entity of that type if there is exactly one, otherwise report
        ambiguity so the caller can ask which one.
        """
        if self.active is None:
            return FocusResult(None, reason="no active workspace")

        graph = self.active.graph
        for entity_id in self._mentions:
            entity = graph.get(entity_id)
            if entity and entity.type == entity_type:
                return FocusResult(entity, reason="most recently mentioned")

        candidates = graph.by_type(entity_type)
        if len(candidates) == 1:
            return FocusResult(candidates[0], reason="only one in project")
        if not candidates:
            return FocusResult(None, reason=f"no {entity_type} in project")
        return FocusResult(None, ambiguous=candidates, reason="multiple candidates")
