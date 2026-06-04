"""Discover the available workspaces and resolve spoken names to them.

The registry is what turns *"argus, open project cressida"* into a concrete
``Workspace``. It scans the workspaces root for project folders and fuzzy-matches
a spoken phrase against every workspace's name and aliases.
"""

from __future__ import annotations

from pathlib import Path

from argus.workspace.loader import load_workspace
from argus.workspace.models import Workspace


class WorkspaceRegistry:
    """Index of every project folder under a workspaces root directory."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._cache: dict[str, Workspace] = {}

    def discover(self) -> list[Workspace]:
        """(Re)load every workspace folder under the root."""
        self._cache.clear()
        if not self.root.is_dir():
            return []
        for child in sorted(self.root.iterdir()):
            if child.is_dir() and (child / "workspace.yaml").is_file():
                workspace = load_workspace(child)
                self._cache[workspace.slug] = workspace
        return list(self._cache.values())

    def all(self) -> list[Workspace]:
        if not self._cache:
            self.discover()
        return list(self._cache.values())

    def get(self, slug: str) -> Workspace | None:
        if not self._cache:
            self.discover()
        return self._cache.get(slug)

    def resolve(self, query: str, threshold: float = 0.5) -> Workspace | None:
        """Best workspace named by ``query`` ("project cressida" -> Cressida)."""
        best: tuple[float, Workspace] | None = None
        for workspace in self.all():
            score = workspace.match_score(query)
            if score >= threshold and (best is None or score > best[0]):
                best = (score, workspace)
        return best[1] if best else None
