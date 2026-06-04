"""Knowledge extraction: let Claude ruminate over a project's docs and propose
additions to its graph. Proposals are *staged for review*, never auto-applied.
"""

from argus.enrich.extractor import enrich_workspace

__all__ = ["enrich_workspace"]
