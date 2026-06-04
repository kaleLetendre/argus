"""The knowledge layer: answer questions from the active context.

Hybrid retrieval, in two stages: try the structured facts on the relevant
entity first (exact), and fall back to RAG over the markdown docs.
"""

from argus.knowledge.query import Answer, answer_question

__all__ = ["Answer", "answer_question"]
