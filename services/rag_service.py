"""
RAG (Retrieval-Augmented Generation) service — Phase 5 predisposition.

Architecture overview for future implementation:
  1. INDEXING: When a guideline document is added/updated, extract its text
     and split into chunks. Store chunks + embeddings in a vector store.
     For PythonAnywhere Free tier, a lightweight local store (e.g. ChromaDB
     or a simple FAISS index persisted to disk) is appropriate.
  2. RETRIEVAL: On each user question, embed the query, find the top-k
     most similar chunks, and assemble a context string.
  3. GENERATION: Pass context + question to an LLM API (e.g. Anthropic
     claude-haiku-4, OpenAI gpt-4o-mini) and stream the answer back.

Current status: all functions return stubs with clear TODO markers.
The chat endpoint in guidelines/routes.py calls ask() and handles the
501 gracefully — the UI shows a "coming soon" notice.
"""
from __future__ import annotations
import os

# ── Index management ──────────────────────────────────────────────────────────

def index_document(filepath: str, filename: str) -> bool:
    """
    Extract text from a PDF or Markdown file and add it to the vector index.
    Returns True on success.

    TODO (Phase 6):
      - PDF: use pdfminer.six or pypdf to extract text pages.
      - MD:  parse with markdown library, strip HTML tags.
      - Chunk text into ~500-token segments with 50-token overlap.
      - Embed each chunk (e.g. sentence-transformers or API embedding).
      - Upsert into vector store keyed by (filename, chunk_index).
    """
    raise NotImplementedError("RAG indexing not yet implemented.")


def remove_document(filename: str) -> bool:
    """
    Remove all chunks belonging to ``filename`` from the vector index.

    TODO (Phase 6): delete by metadata filter on filename key.
    """
    raise NotImplementedError("RAG index removal not yet implemented.")


def list_indexed() -> list[str]:
    """
    Return a list of filenames currently in the vector index.

    TODO (Phase 6): query vector store for distinct filename metadata values.
    """
    return []


# ── Question answering ────────────────────────────────────────────────────────

def ask(question: str, top_k: int = 4) -> dict:
    """
    Answer a question using the indexed guideline documents (RAG pipeline).

    Returns:
        {
            "answer":  str,
            "sources": [{"filename": str, "excerpt": str}, ...],
            "status":  "ok" | "no_index" | "not_implemented",
        }

    TODO (Phase 6):
      1. Embed ``question``.
      2. Retrieve top_k chunks from vector store.
      3. Build a prompt:
             System: "You are a lab safety assistant. Answer using only
                      the provided context. If unsure, say so."
             User:   f"Context:\n{context}\n\nQuestion: {question}"
      4. Call LLM API (stream optional).
      5. Return answer + source excerpts for citation display.
    """
    return {
        "answer":  None,
        "sources": [],
        "status":  "not_implemented",
    }
