"""Resolve generated documents from the authenticated workspace transcript."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

DOCUMENT_REF = r"document-[a-f0-9]{16}"
DOCUMENT_FILENAME = r"[A-Za-z0-9][A-Za-z0-9_-]{0,55}\.md"
DOCUMENT_LIMIT = 3800


@dataclass(frozen=True, slots=True)
class WorkspaceDocument:
    ref: str
    filename: str
    markdown: str

    def metadata(self) -> dict:
        return {"document_ref": self.ref, "filename": self.filename}


def workspace_document_ref(run_id: str, call_id: str) -> str:
    digest = hashlib.sha256(f"{run_id}\0{call_id}".encode()).hexdigest()
    return f"document-{digest[:16]}"


def completed_workspace_documents(
    events: list[dict], continuing_runs: frozenset[str] = frozenset()
) -> dict[str, WorkspaceDocument]:
    available_runs = continuing_runs | {
        event.get("run_id") for event in events
        if event.get("type") == "end" and event.get("status") == "completed"
    }
    documents: dict[str, WorkspaceDocument] = {}
    for event in events:
        run_id, call_id = event.get("run_id"), event.get("call_id")
        if (
            event.get("type") != "tool_result"
            or run_id not in available_runs
            or not isinstance(run_id, str)
            or not isinstance(call_id, str)
        ):
            continue
        view = event.get("view")
        if not isinstance(view, dict) or view.get("kind") != "markdown":
            continue
        filename, markdown = view.get("filename"), view.get("markdown")
        if (
            not isinstance(filename, str)
            or not re.fullmatch(DOCUMENT_FILENAME, filename)
            or not isinstance(markdown, str)
            or not markdown.strip()
            or len(markdown) > DOCUMENT_LIMIT
        ):
            continue
        ref = view.get("document_ref") or workspace_document_ref(run_id, call_id)
        if isinstance(ref, str) and re.fullmatch(DOCUMENT_REF, ref):
            documents[ref] = WorkspaceDocument(ref, filename, markdown)
    return documents


def select_workspace_document(
    documents: dict[str, WorkspaceDocument], selection: str
) -> WorkspaceDocument | None:
    if selection in documents:
        return documents[selection]
    return next((
        document for document in reversed(documents.values())
        if selection == "latest" or document.filename == selection
    ), None)
