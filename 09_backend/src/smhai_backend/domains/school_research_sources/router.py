"""Scope-C read-only API for the currently pinned research source package."""

from __future__ import annotations

import asyncio
import re
from tempfile import TemporaryFile
from typing import Any
from urllib.parse import unquote

from database_layer.provenance import is_public_demo_school_ref
from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import CsrfActor, CurrentActor
from smhai_backend.domains.models import BackendRole

from . import library
from .schemas import ResearchSourceCatalogPageDto, ResearchSourceDetailDto

router = APIRouter(prefix="/school/research-sources", tags=["school-research-sources"])
_SOURCE_REF = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
_LIBRARY_REF = re.compile(r"LIB_[a-f0-9]{32}\Z")
_UPLOAD_SLOTS = asyncio.Semaphore(2)


def _library_path(request: Request, actor: CurrentActor):
    if (
        request.app.state.container.settings.public_demo.site_key is None
        or actor.scope_profile != "school_tenant"
        or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
        or type(actor.school_id) is not int
        or actor.school_id <= 0
        or not actor.school_ref
        or not is_public_demo_school_ref(actor.school_ref)
    ):
        raise error(ErrorCode.FORBIDDEN, detail="access denied")
    return library.library_path(actor.school_ref)


def _private_response(request: Request, data: dict, status: int = 200) -> JSONResponse:
    context = current_request_context(request)
    return JSONResponse(
        {"request_id": context.request_id, "trace_id": context.trace_id, "data": data},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/library/documents", response_model=None)
async def list_library_documents(request: Request, actor: CurrentActor):
    path = _library_path(request, actor)
    records = await run_in_threadpool(library.list_documents, path)
    return _private_response(request, {"items": records})


@router.post("/library/documents", response_model=None)
async def import_library_document(request: Request, actor: CsrfActor):
    path = _library_path(request, actor)
    encoded_name = request.headers.get("x-psynova-filename", "")
    if (
        request.headers.get("x-psynova-reviewed") != "yes"
        or request.headers.get("content-type") != "application/octet-stream"
        or not 1 <= len(encoded_name) <= 1800
    ):
        raise error(ErrorCode.VALIDATION_FAILED, detail="reviewed document is required")
    if _UPLOAD_SLOTS.locked():
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="document processing is busy", retryable=True)
    async with _UPLOAD_SLOTS:
        with TemporaryFile() as content:
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > library.MAX_UPLOAD:
                    raise error(ErrorCode.VALIDATION_FAILED, detail="document is too large")
                await run_in_threadpool(content.write, chunk)
            record, created = await run_in_threadpool(
                library.add_document, path, unquote(encoded_name), content, actor.user_id,
            )
    return _private_response(request, {"document": record, "created": created}, 201 if created else 200)


@router.delete("/library/documents/{document_ref}", response_model=None)
async def withdraw_library_document(request: Request, actor: CsrfActor, document_ref: str):
    path = _library_path(request, actor)
    if not _LIBRARY_REF.fullmatch(document_ref):
        raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="document was not found")
    await run_in_threadpool(library.withdraw_document, path, document_ref, actor.user_id)
    return _private_response(request, {"withdrawn": True})


@router.post("/library/search", response_model=None)
async def search_library_documents(request: Request, actor: CsrfActor, payload: dict[str, str]):
    _library_path(request, actor)
    assert actor.school_ref is not None
    query = payload.get("query", "").strip()
    if set(payload) != {"query"} or not 1 <= len(query) <= 160:
        raise error(ErrorCode.VALIDATION_FAILED, detail="invalid search query")
    matches = await library.retrieve(actor.school_ref, query)
    return _private_response(request, {"items": matches})


def _service(request: Request, actor: Any):
    if (
        actor.scope_profile != "school_tenant"
        or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
        or type(actor.school_id) is not int
        or actor.school_id <= 0
        or type(actor.school_ref) is not str
        or not actor.school_ref
    ):
        raise error(ErrorCode.FORBIDDEN, detail="access denied")
    service = getattr(request.app.state.container, "school_research_sources", None)
    if service is None:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research source catalog is not configured",
            retryable=True,
        )
    return service


def _response(request: Request, data):
    context = current_request_context(request)
    return JSONResponse(
        {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "data": data.model_dump(mode="json"),
        }
    )


def _closed_query(request: Request) -> None:
    allowed = {"offset", "limit"}
    if set(request.query_params) - allowed or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise error(ErrorCode.VALIDATION_FAILED, detail="research source query is invalid")


@router.get("/catalog", response_model=None)
async def list_sources(
    request: Request,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=10_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    _closed_query(request)
    data = ResearchSourceCatalogPageDto.model_validate(
        _service(request, actor).list_sources(actor, limit=limit, offset=offset)
    )
    return _response(request, data)


@router.get("/{source_ref}", response_model=None)
async def get_source(
    request: Request,
    source_ref: str,
    actor: CurrentActor,
):
    if not re.fullmatch(_SOURCE_REF, source_ref):
        raise error(ErrorCode.VALIDATION_FAILED, detail="source reference is invalid")
    data = ResearchSourceDetailDto.model_validate(
        _service(request, actor).get_source(actor, source_ref)
    )
    return _response(request, data)
