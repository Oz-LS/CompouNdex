"""
Guidelines section.
Serves PDF and Markdown documents from static/guidelines/.
Provides inline Markdown rendering (server-side, via Python-Markdown).
Includes a stub /api/ask endpoint wired to rag_service for future RAG integration.
"""
from __future__ import annotations
import os
import math
from datetime import datetime
from flask import (
    render_template, request, jsonify, abort,
    send_from_directory, current_app
)
from . import guidelines_bp


# ── Directory helpers ─────────────────────────────────────────────────────────

def _guidelines_dir() -> str:
    return os.path.join(current_app.static_folder, "guidelines")


ALLOWED_EXTENSIONS = {".pdf", ".md"}


def _list_documents() -> list[dict]:
    """Return sorted metadata list for every guideline document."""
    gdir = _guidelines_dir()
    os.makedirs(gdir, exist_ok=True)
    docs = []
    for fname in sorted(os.listdir(gdir)):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            continue
        fpath = os.path.join(gdir, fname)
        if not os.path.isfile(fpath):
            continue
        stat  = os.stat(fpath)
        docs.append({
            "filename": fname,
            "type":     ext.lstrip("."),
            "size_kb":  math.ceil(stat.st_size / 1024),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
            "title":    _title_from_filename(fname),
        })
    return docs


def _title_from_filename(fname: str) -> str:
    name = os.path.splitext(fname)[0]
    name = name.lstrip("0123456789_- ")
    return name.replace("_", " ").replace("-", " ").title()


def _safe_path(filename: str) -> str | None:
    gdir   = os.path.realpath(_guidelines_dir())
    target = os.path.realpath(os.path.join(gdir, filename))
    if target.startswith(gdir + os.sep) or target == gdir:
        return target
    return None


def _render_markdown(filepath: str) -> str:
    try:
        import markdown as md_lib
    except ImportError:
        return ("<p class='text-danger'>Python-Markdown not installed. "
                "Run <code>pip install Markdown</code>.</p>")
    with open(filepath, encoding="utf-8") as f:
        text = f.read()
    extensions = ["tables", "fenced_code", "toc", "nl2br", "sane_lists"]
    return md_lib.markdown(text, extensions=extensions)


# ── Page ──────────────────────────────────────────────────────────────────────

@guidelines_bp.route("/", methods=["GET"])
def index():
    documents = _list_documents()
    selected  = request.args.get("doc", "")
    return render_template(
        "guidelines/index.html",
        active="guidelines",
        documents=documents,
        selected=selected,
    )


# ── Serve raw file (PDF → iframe src, MD → download) ─────────────────────────

@guidelines_bp.route("/view/<path:filename>")
def view_document(filename):
    safe = _safe_path(filename)
    if not safe:
        abort(403)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS or not os.path.isfile(safe):
        abort(404)
    return send_from_directory(_guidelines_dir(), filename)


# ── Render Markdown as HTML fragment ─────────────────────────────────────────

@guidelines_bp.route("/api/render/<path:filename>")
def api_render(filename):
    safe = _safe_path(filename)
    if not safe:
        return jsonify({"status": "error", "message": "Forbidden."}), 403
    if not os.path.isfile(safe):
        return jsonify({"status": "error", "message": "File not found."}), 404
    if os.path.splitext(filename)[1].lower() != ".md":
        return jsonify({"status": "error", "message": "Not a Markdown file."}), 400
    html = _render_markdown(safe)
    return jsonify({"status": "ok", "html": html})


# ── Document list (AJAX) ──────────────────────────────────────────────────────

@guidelines_bp.route("/api/documents")
def api_documents():
    return jsonify({"documents": _list_documents()})


# ── RAG / LLM ask (stub) ──────────────────────────────────────────────────────

@guidelines_bp.route("/api/ask", methods=["POST"])
def api_ask():
    from services import rag_service
    data     = request.get_json(force=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"status": "error", "message": "No question provided."}), 400
    try:
        result = rag_service.ask(question)
    except NotImplementedError:
        result = {"status": "not_implemented", "answer": None, "sources": []}
    if result["status"] == "not_implemented":
        return jsonify({
            "status":  "not_implemented",
            "message": "The AI assistant is not yet available. It will be enabled in a future update.",
        }), 501
    return jsonify(result)
