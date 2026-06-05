"""Conversation session state: which context is active and what it's focused on.

Two pieces of state move as you talk to Argus:

* the **active workspace** (set explicitly by "open project cressida"), and
* the **focused entity**, which is *inferred from conversation* rather than set
  by command. As entities get mentioned they're pushed onto a short history;
  "my current engine" then resolves to the most recently referenced engine, or,
  if none has come up yet, to the only engine in the project.

Focus inference reads candidates from the store (Neo4j) but the mention history
itself lives here, in memory, for the life of the conversation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from argus.workspace.models import Entity, Workspace


@dataclass
class FocusResult:
    """Outcome of trying to infer "my current <type>"."""

    entity: Entity | None
    ambiguous: list[Entity] = field(default_factory=list)
    reason: str = ""


class Session:
    """Mutable per-conversation state layered over the canonical store."""

    def __init__(self) -> None:
        self.active: Workspace | None = None
        # Most-recent-first entities mentioned this conversation.
        self._mentions: list[Entity] = []

    # -- navigation ---------------------------------------------------------
    def activate(self, workspace: Workspace) -> None:
        """Switch context. Focus history does not carry across projects."""
        self.active = workspace
        self._mentions.clear()

    # -- focus tracking -----------------------------------------------------
    def note_mention(self, entity: Entity) -> None:
        """Record that an entity just came up, so focus can be inferred later.
        Dedupes on the stable ``uid`` (falling back to ``id``) so same-id
        entities from different projects never collapse."""
        key = entity.uid or entity.id
        self._mentions = [entity] + [m for m in self._mentions if (m.uid or m.id) != key]

    def infer_focus(self, entity_type: str, store) -> FocusResult:
        """Resolve "my current <entity_type>" from conversation so far.

        Order of preference: most recently mentioned entity of that type, then
        the unique entity of that type in the project, otherwise report ambiguity
        so the caller can ask which one.
        """
        if self.active is None:
            return FocusResult(None, reason="no active workspace")

        for entity in self._mentions:
            if entity.type == entity_type:
                return FocusResult(entity, reason="most recently mentioned")

        candidates = store.by_type(self.active.slug, entity_type)
        if len(candidates) == 1:
            return FocusResult(candidates[0], reason="only one in project")
        if not candidates:
            return FocusResult(None, reason=f"no {entity_type} in project")
        return FocusResult(None, ambiguous=candidates, reason="multiple candidates")
