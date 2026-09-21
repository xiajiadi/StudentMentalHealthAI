"""Trusted, immutable evidence binding for one Backend retrieval transaction.

The RAG adapter owns retrieval.  This module owns the short-lived Backend
snapshot that is allowed to cross the generation boundary.  It deliberately
does not infer a corpus, index, rank, score, or snapshot identity.  Values in
the bundle come from the observed ``RetrievalResult``/``KnowledgeChunk``
projection or from server supplied transaction linkage and eligibility policy.

The public contract is intentionally small:

* :func:`build_retrieval_evidence_bundle` copies an observed retrieval into a
  recursively immutable snapshot and computes its deterministic hash;
* :meth:`RetrievalEvidenceBundle.require_eligible` is the fail-closed gate;
* :meth:`RetrievalEvidenceBundle.validate_citations` checks candidate citation
  identity, content hash, and bundle membership;
* :meth:`RetrievalEvidenceBundle.resolve_citation` resolves display metadata
  from the same already-bound object and rechecks its hash on every call.

This is a Backend integration helper, not a replacement for RAG eligibility
or retrieval algorithms.  It never creates a global snapshot identifier and
never derives ``content_hash`` from text when the upstream response omits it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from .rag import KnowledgeChunk, RetrievalResult

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


_MISSING = object()
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_KNOWN_CHUNK_FIELDS = frozenset(
    {
        "schema_version",
        "chunk_id",
        "document_id",
        "text",
        "content_type",
        "location",
        "citation",
        "population_scope",
        "role_scope",
        "risk_scope",
        "review_status",
        "rights_status",
        "content_hash",
        "embedding",
    }
)
_PROVENANCE_FIELDS = (
    "index_id",
    "index_version",
    "corpus_version",
    "corpus_build_id",
    "build_id",
    "snapshot_id",
    "run_id",
    "query_id",
    "trace_id",
    "request_id",
)


class EvidenceBindingError(ValueError):
    """Base error for a retrieval evidence binding refusal."""

    code = "EVIDENCE_BINDING_FAILED"

    def __init__(self, detail: str, *, code: str | None = None) -> None:
        self.detail = detail
        if code is not None:
            self.code = code
        super().__init__(detail)


class EvidenceShapeError(EvidenceBindingError):
    """The observed RAG response cannot be represented safely."""

    code = "EVIDENCE_SHAPE_INVALID"


class BundleIntegrityError(EvidenceBindingError):
    """The immutable snapshot no longer matches its recorded digest."""

    code = "EVIDENCE_BUNDLE_TAMPERED"


class EvidenceEligibilityError(EvidenceBindingError):
    """A bundle contains no generation eligible evidence."""

    code = "EVIDENCE_NOT_ELIGIBLE"

    def __init__(self, detail: str, *, reasons: Sequence[str] = ()) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons if reason))
        super().__init__(detail)


class CitationBindingError(EvidenceBindingError):
    """A candidate citation is unknown, tampered, or from another retrieval."""

    code = "CITATION_BINDING_FAILED"


class CitationMembershipError(CitationBindingError):
    """A citation does not belong to the prompt-bound evidence set."""

    code = "CITATION_NOT_A_MEMBER"


class CitationIntegrityError(CitationBindingError):
    """A citation identity or content hash does not match the bundle."""

    code = "CITATION_INTEGRITY_MISMATCH"


class _FrozenMapping(Mapping[str, Any]):
    """A recursively immutable, JSON-shaped mapping.

    ``MappingProxyType`` is not recursively immutable and is awkward to copy
    safely at the boundary.  This tiny mapping stores sorted key/value pairs,
    which also makes accidental mutation of nested RAG data impossible.
    """

    __slots__ = ("_items", "_index")

    def __init__(self, value: Mapping[str, Any]) -> None:
        items: list[tuple[str, Any]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise EvidenceShapeError("observed JSON object keys must be strings")
            items.append((key, _freeze(item)))
        items.sort(key=lambda pair: pair[0])
        object.__setattr__(self, "_items", tuple(items))
        object.__setattr__(self, "_index", MappingProxyType(dict(items)))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("frozen evidence mappings cannot be modified")

    def __getitem__(self, key: str) -> Any:
        return self._index[key]

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"_FrozenMapping({self.to_dict()!r})"

    def to_dict(self) -> dict[str, JsonValue]:
        return {key: _thaw(value) for key, value in self._items}


def _freeze(value: Any) -> Any:
    """Convert JSON-shaped values to recursively immutable values."""

    if isinstance(value, _FrozenMapping):
        return value
    if isinstance(value, Mapping):
        return _FrozenMapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        raise EvidenceShapeError("observed sets are not JSON values")
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvidenceShapeError("observed numeric provenance must be finite")
        return value
    raise EvidenceShapeError(f"observed value has unsupported type: {type(value).__name__}")


def _thaw(value: Any) -> JsonValue:
    if isinstance(value, _FrozenMapping):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return cast(JsonValue, value)


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            _thaw(_freeze(value)),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise EvidenceShapeError("evidence is not canonical JSON") from exc


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _copy_json(value: Any) -> JsonValue:
    """Copy and validate an observed model/mapping without sharing mutables."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    frozen = _freeze(value)
    return _thaw(frozen)


def _mapping(value: Any, *, field: str) -> Mapping[str, Any] | None:
    if value is None or value is _MISSING:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        raise EvidenceShapeError(f"{field} must be an object or null")
    return cast(Mapping[str, Any], value)


def _optional_string(value: Any, *, field: str) -> str | None:
    if value is None or value is _MISSING:
        return None
    if not isinstance(value, str) or not value.strip():
        raise EvidenceShapeError(f"{field} must be a non-empty string or null")
    return value


def _required_identifier(value: Any, *, field: str, prefix: str | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceShapeError(f"{field} is missing or invalid")
    if prefix is not None and not value.startswith(prefix):
        raise EvidenceShapeError(f"{field} has an invalid identifier prefix")
    if not _ID_RE.fullmatch(value):
        raise EvidenceShapeError(f"{field} has an invalid identifier")
    return value


def _optional_scope(value: Any, *, field: str) -> tuple[str, ...] | None:
    if value is None or value is _MISSING:
        return None
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        raise EvidenceShapeError(f"{field} must be an array of strings or null")
    result = tuple(item for item in value if isinstance(item, str) and item.strip())
    if len(result) != len(value):
        raise EvidenceShapeError(f"{field} must contain only non-empty strings")
    return tuple(dict.fromkeys(result))


def _get(mapping: Mapping[str, Any], key: str) -> Any:
    return mapping[key] if key in mapping else _MISSING


def _trace_field(trace: Mapping[str, Any] | None, key: str) -> Any:
    if trace is None:
        return None
    value = trace.get(key)
    if value is not None:
        return _copy_json(value)
    # Accepted RAG traces have used a few explicit aliases.  Only values that
    # are actually present are copied; this does not create an identifier.
    aliases = {
        "corpus_build_id": ("corpus_build", "build_id"),
        "index_id": ("index",),
        "index_version": ("index_revision",),
        "snapshot_id": ("snapshot",),
        "run_id": ("retrieval_run_id",),
    }
    for alias in aliases.get(key, ()):
        if alias in trace and trace[alias] is not None:
            return _copy_json(trace[alias])
    return None


def _retrieval_parts(
    retrieval: RetrievalResult | Mapping[str, Any],
) -> tuple[str, Sequence[Any], str | None, Mapping[str, Any] | None]:
    if isinstance(retrieval, RetrievalResult):
        return retrieval.retrieval_id, retrieval.chunks, retrieval.label, retrieval.trace
    if not isinstance(retrieval, Mapping):
        raise EvidenceShapeError("retrieval must be a RetrievalResult or object")
    retrieval_id = _required_identifier(
        _get(retrieval, "retrieval_id"), field="retrieval_id", prefix="RETR_"
    )
    chunks = _get(retrieval, "chunks")
    if not isinstance(chunks, Sequence) or isinstance(chunks, (str, bytes, bytearray)):
        raise EvidenceShapeError("retrieval chunks must be an array")
    label_value = _get(retrieval, "label")
    label = _optional_string(label_value, field="label")
    trace = _mapping(_get(retrieval, "trace"), field="trace")
    return retrieval_id, chunks, label, trace


@dataclass(frozen=True, slots=True)
class EligibilityPolicy:
    """Server-derived eligibility requirements for this retrieval transaction."""

    target_population: str | None = None
    target_role: str | None = None
    risk_level: str | None = None
    required_review_status: str = "approved"
    required_rights_status: str = "verified"

    def __post_init__(self) -> None:
        for name in (
            "target_population",
            "target_role",
            "risk_level",
            "required_review_status",
            "required_rights_status",
        ):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise EvidenceShapeError(f"eligibility {name} must be a non-empty string or null")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "target_population": self.target_population,
            "target_role": self.target_role,
            "risk_level": self.risk_level,
            "required_review_status": self.required_review_status,
            "required_rights_status": self.required_rights_status,
        }


@dataclass(frozen=True, slots=True)
class EvidenceEligibility:
    eligible: bool
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {"eligible": self.eligible, "reason_codes": list(self.reason_codes)}


@dataclass(frozen=True, slots=True)
class RetrievalEvidence:
    """One immutable chunk plus the exact observed projection used for binding."""

    citation_id: str
    evidence_id: str
    payload: _FrozenMapping
    eligibility: EvidenceEligibility

    @property
    def schema_version(self) -> str | None:
        return cast(str | None, self.payload.get("schema_version"))

    @property
    def chunk_id(self) -> str:
        return cast(str, self.payload["chunk_id"])

    @property
    def document_id(self) -> str:
        return cast(str, self.payload["document_id"])

    @property
    def text(self) -> str | None:
        return cast(str | None, self.payload.get("text"))

    @property
    def content_hash(self) -> str | None:
        return cast(str | None, self.payload.get("content_hash"))

    @property
    def citation(self) -> Mapping[str, Any]:
        value = self.payload.get("citation")
        return value if isinstance(value, Mapping) else {}

    @property
    def locator(self) -> str | None:
        value = self.citation.get("locator")
        return cast(str | None, value)

    @property
    def location(self) -> Mapping[str, Any] | None:
        value = self.payload.get("location")
        return value if isinstance(value, Mapping) else None

    @property
    def population_scope(self) -> tuple[str, ...] | None:
        value = self.payload.get("population_scope")
        return tuple(value) if isinstance(value, tuple) else None

    @property
    def role_scope(self) -> tuple[str, ...] | None:
        value = self.payload.get("role_scope")
        return tuple(value) if isinstance(value, tuple) else None

    @property
    def risk_scope(self) -> tuple[str, ...] | None:
        value = self.payload.get("risk_scope")
        return tuple(value) if isinstance(value, tuple) else None

    @property
    def review_status(self) -> str | None:
        return cast(str | None, self.payload.get("review_status"))

    @property
    def rights_status(self) -> str | None:
        return cast(str | None, self.payload.get("rights_status"))

    @property
    def observed(self) -> Mapping[str, Any]:
        value = self.payload.get("observed")
        return value if isinstance(value, Mapping) else {}

    @property
    def rank(self) -> int | float | str | None:
        value = self.observed.get("rank")
        return cast(int | float | str | None, value)

    @property
    def score(self) -> int | float | str | None:
        value = self.observed.get("score")
        return cast(int | float | str | None, value)

    def to_dict(self) -> dict[str, JsonValue]:
        payload = cast(dict[str, JsonValue], self.payload.to_dict())
        payload["citation_id"] = self.citation_id
        payload["evidence_id"] = self.evidence_id
        payload["eligibility"] = self.eligibility.to_dict()
        return payload

    def prompt_citation(self) -> dict[str, JsonValue]:
        """Return the exact two-field shape accepted by D3-3 PromptCitation."""

        return {"source_chunk_id": self.chunk_id, "locator": self.locator}


@dataclass(frozen=True, slots=True)
class OpaqueCitationReference:
    """A candidate-facing citation reference bound to one evidence bundle."""

    evidence_id: str
    source_chunk_id: str
    document_id: str
    content_hash: str | None
    locator: str | None
    retrieval_id: str
    bundle_hash: str

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "evidence_id": self.evidence_id,
            "source_chunk_id": self.source_chunk_id,
            "document_id": self.document_id,
            "content_hash": self.content_hash,
            "locator": self.locator,
            "retrieval_id": self.retrieval_id,
            "bundle_hash": self.bundle_hash,
        }

    def to_prompt_dict(self) -> dict[str, JsonValue]:
        return {"source_chunk_id": self.source_chunk_id, "locator": self.locator}


@dataclass(frozen=True, slots=True)
class RetrievalEvidenceBundle:
    """Exact immutable evidence selected by one retrieval transaction."""

    retrieval_id: str
    linkage: _FrozenMapping
    provenance: _FrozenMapping
    policy: _FrozenMapping
    items: tuple[RetrievalEvidence, ...]
    bundle_hash: str

    @property
    def chunks(self) -> tuple[RetrievalEvidence, ...]:
        return self.items

    @property
    def eligible(self) -> bool:
        return bool(self.items) and all(item.eligibility.eligible for item in self.items)

    @property
    def chunk_ids(self) -> tuple[str, ...]:
        return tuple(item.chunk_id for item in self.items)

    @property
    def citation_ids(self) -> tuple[str, ...]:
        return tuple(item.citation_id for item in self.items)

    @property
    def canonical_payload(self) -> dict[str, JsonValue]:
        """Return a detached payload; changing it cannot mutate this bundle."""

        return cast(dict[str, JsonValue], self._payload_without_hash())

    @property
    def canonical_json(self) -> str:
        return _canonical_json(self.canonical_payload)

    @property
    def prefixed_bundle_hash(self) -> str:
        return f"sha256:{self.bundle_hash}"

    @classmethod
    def from_retrieval(
        cls,
        retrieval: RetrievalResult | Mapping[str, Any],
        *,
        transaction_id: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        policy: EligibilityPolicy | Mapping[str, Any] | None = None,
        strict_eligibility: bool = True,
    ) -> RetrievalEvidenceBundle:
        return build_retrieval_evidence_bundle(
            retrieval,
            transaction_id=transaction_id,
            request_id=request_id,
            trace_id=trace_id,
            policy=policy,
            strict_eligibility=strict_eligibility,
        )

    def _payload_without_hash(self) -> dict[str, JsonValue]:
        return {
            "bundle_type": "RetrievalEvidenceBundle",
            "bundle_version": "1",
            "retrieval_id": self.retrieval_id,
            "linkage": cast(dict[str, JsonValue], self.linkage.to_dict()),
            "provenance": cast(dict[str, JsonValue], self.provenance.to_dict()),
            "eligibility_policy": cast(dict[str, JsonValue], self.policy.to_dict()),
            "chunks": [item.to_dict() for item in self.items],
        }

    def to_dict(self) -> dict[str, JsonValue]:
        value = self.canonical_payload
        value["bundle_hash"] = self.bundle_hash
        return value

    def verify(self) -> None:
        """Recompute the hash and reject mutation/substitution before use."""

        expected = _sha256(self.canonical_json)
        if not hmac_compare(expected, self.bundle_hash):
            raise BundleIntegrityError("retrieval evidence bundle hash does not match its payload")
        if self.retrieval_id != self.provenance.get("retrieval_id"):
            raise BundleIntegrityError("retrieval evidence retrieval identity changed")
        for item in self.items:
            if item.payload.get("chunk_id") != item.chunk_id:
                raise BundleIntegrityError("retrieval evidence chunk identity changed")

    def require_eligible(self) -> None:
        """Fail closed before trusted prompt/generation composition."""

        self.verify()
        if self.eligible:
            return
        reasons: list[str] = []
        if not self.items:
            reasons.append("NO_RETRIEVED_CHUNKS")
        for item in self.items:
            reasons.extend(item.eligibility.reason_codes)
        raise EvidenceEligibilityError(
            "retrieval evidence is not eligible for generation",
            reasons=tuple(dict.fromkeys(reasons)),
        )

    def trusted_chunks(self) -> tuple[dict[str, JsonValue], ...]:
        """Return detached knowledge projections only after the eligibility gate."""

        self.require_eligible()
        trusted: list[dict[str, JsonValue]] = []
        for item in self.items:
            projection = cast(dict[str, JsonValue], _copy_json(item.payload.to_dict()))
            projection.pop("observed", None)
            trusted.append(projection)
        return tuple(trusted)

    def prompt_citations(self) -> tuple[dict[str, JsonValue], ...]:
        self.require_eligible()
        return tuple(item.prompt_citation() for item in self.items)

    def citation_references(self) -> tuple[OpaqueCitationReference, ...]:
        self.require_eligible()
        return tuple(self._reference(item) for item in self.items)

    def reference_for(self, chunk_id: str) -> OpaqueCitationReference:
        self.require_eligible()
        matches = [item for item in self.items if item.chunk_id == chunk_id]
        if len(matches) != 1:
            raise CitationMembershipError("citation chunk is not a unique bundle member")
        return self._reference(matches[0])

    def _reference(self, item: RetrievalEvidence) -> OpaqueCitationReference:
        return OpaqueCitationReference(
            evidence_id=item.evidence_id,
            source_chunk_id=item.chunk_id,
            document_id=item.document_id,
            content_hash=item.content_hash,
            locator=item.locator,
            retrieval_id=self.retrieval_id,
            bundle_hash=self.bundle_hash,
        )

    def validate_citation(
        self,
        citation: OpaqueCitationReference | Mapping[str, Any] | str,
        *,
        require_integrity_fields: bool = True,
    ) -> RetrievalEvidence:
        """Validate one candidate citation against this exact bundle.

        Candidate output should carry ``evidence_id``, ``source_chunk_id``,
        ``document_id``, ``content_hash``, ``retrieval_id`` and
        ``bundle_hash``.  Prompt-facing D3-3 citations intentionally contain
        only ``source_chunk_id`` and ``locator``; callers validating that
        pre-generation shape should use :meth:`validate_prompt_citation`.
        """

        self.verify()
        value = _citation_mapping(citation)
        if value.get("bundle_hash") is not None and value.get("bundle_hash") != self.bundle_hash:
            raise CitationIntegrityError("citation belongs to a different evidence bundle")
        if value.get("retrieval_id") is not None and value.get("retrieval_id") != self.retrieval_id:
            raise CitationIntegrityError("citation belongs to a different retrieval")
        item = self._find_citation_item(value)
        _assert_equal_if_present(value, "source_chunk_id", item.chunk_id)
        _assert_equal_if_present(value, "chunk_id", item.chunk_id)
        _assert_equal_if_present(value, "document_id", item.document_id)
        _assert_equal_if_present(value, "content_hash", item.content_hash)
        _assert_equal_if_present(value, "locator", item.locator)
        if require_integrity_fields:
            missing = [key for key in ("document_id", "content_hash") if key not in value]
            if missing:
                raise CitationIntegrityError(
                    f"citation is missing required integrity fields: {', '.join(missing)}"
                )
        if not item.eligibility.eligible:
            raise EvidenceEligibilityError(
                "citation refers to ineligible evidence",
                reasons=item.eligibility.reason_codes,
            )
        return item

    def validate_prompt_citation(
        self, citation: Mapping[str, Any] | OpaqueCitationReference
    ) -> RetrievalEvidence:
        """Validate the minimal pre-generation D3-3 ``PromptCitation`` shape."""

        if isinstance(citation, OpaqueCitationReference):
            return self.validate_citation(citation)
        value = _citation_mapping(citation)
        if set(value) - {"source_chunk_id", "locator"}:
            raise CitationIntegrityError("prompt citation contains untrusted fields")
        self.require_eligible()
        item = self._find_citation_item(value)
        _assert_equal_if_present(value, "source_chunk_id", item.chunk_id)
        _assert_equal_if_present(value, "locator", item.locator)
        return item

    def validate_citations(
        self,
        citations: Iterable[OpaqueCitationReference | Mapping[str, Any] | str],
        *,
        require_integrity_fields: bool = True,
    ) -> tuple[RetrievalEvidence, ...]:
        self.verify()
        resolved: list[RetrievalEvidence] = []
        seen: set[str] = set()
        for citation in citations:
            item = self.validate_citation(
                citation,
                require_integrity_fields=require_integrity_fields,
            )
            if item.evidence_id in seen:
                raise CitationMembershipError(
                    "candidate citations contain a duplicate evidence member"
                )
            seen.add(item.evidence_id)
            resolved.append(item)
        return tuple(resolved)

    def resolve_citation(
        self,
        citation: OpaqueCitationReference | Mapping[str, Any] | str,
        *,
        require_integrity_fields: bool = True,
    ) -> dict[str, JsonValue]:
        """Resolve visible citation metadata from this same bound bundle.

        Hash verification runs immediately before lookup.  A caller that swaps
        or mutates the bundle between generation and display therefore gets an
        integrity error instead of a second retrieval-backed citation.
        """

        item = self.validate_citation(
            citation,
            require_integrity_fields=require_integrity_fields,
        )
        return {
            "citation_id": item.citation_id,
            "evidence_id": item.evidence_id,
            "chunk_id": item.chunk_id,
            "document_id": item.document_id,
            "title": cast(str | None, item.citation.get("title")),
            "organization": cast(str | None, item.citation.get("organization")),
            "locator": item.locator,
            "content_hash": item.content_hash,
            "retrieval_id": self.retrieval_id,
            "bundle_hash": self.bundle_hash,
        }

    def _find_citation_item(self, value: Mapping[str, Any]) -> RetrievalEvidence:
        evidence_id = value.get("evidence_id")
        source_chunk_id = value.get("source_chunk_id", value.get("chunk_id"))
        citation_id = value.get("citation_id")
        matches: Sequence[RetrievalEvidence] = self.items
        if evidence_id is not None:
            matches = tuple(item for item in matches if item.evidence_id == evidence_id)
        elif source_chunk_id is not None:
            matches = tuple(item for item in matches if item.chunk_id == source_chunk_id)
        elif citation_id is not None:
            matches = tuple(item for item in matches if item.citation_id == citation_id)
        else:
            raise CitationMembershipError("citation has no evidence or chunk identifier")
        if not matches:
            raise CitationMembershipError("citation is not a member of the bound retrieval")
        if len(matches) > 1:
            raise CitationMembershipError("citation does not identify a unique bundle member")
        return cast(Sequence[RetrievalEvidence], matches)[0]


def _citation_mapping(
    citation: OpaqueCitationReference | Mapping[str, Any] | str,
) -> Mapping[str, Any]:
    if isinstance(citation, OpaqueCitationReference):
        return citation.to_dict()
    if isinstance(citation, str):
        return {"evidence_id": citation}
    if isinstance(citation, Mapping):
        return citation
    raise CitationBindingError("citation must be an opaque reference, object, or evidence id")


def _assert_equal_if_present(value: Mapping[str, Any], key: str, expected: Any) -> None:
    if key in value and value[key] != expected:
        raise CitationIntegrityError(f"citation {key} does not match bound evidence")


def hmac_compare(left: str, right: str) -> bool:
    """Constant-time comparison for hexadecimal bundle digests."""

    try:
        return hmac.compare_digest(left, right)
    except TypeError:
        return False


def _policy(value: EligibilityPolicy | Mapping[str, Any] | None) -> EligibilityPolicy:
    if value is None:
        return EligibilityPolicy()
    if isinstance(value, EligibilityPolicy):
        return value
    if not isinstance(value, Mapping):
        raise EvidenceShapeError("eligibility policy must be an object")
    return EligibilityPolicy(
        target_population=cast(str | None, value.get("target_population")),
        target_role=cast(str | None, value.get("target_role")),
        risk_level=cast(str | None, value.get("risk_level")),
        required_review_status=str(value.get("required_review_status", "approved")),
        required_rights_status=str(value.get("required_rights_status", "verified")),
    )


def _eligibility(payload: Mapping[str, Any], policy: EligibilityPolicy) -> EvidenceEligibility:
    reasons: list[str] = []
    if payload.get("chunk_id") is None:
        reasons.append("MISSING_CHUNK_ID")
    if payload.get("document_id") is None:
        reasons.append("MISSING_DOCUMENT_ID")
    if payload.get("content_hash") is None:
        reasons.append("MISSING_CONTENT_HASH")
    citation = payload.get("citation")
    locator = citation.get("locator") if isinstance(citation, Mapping) else None
    if not isinstance(locator, str) or not locator.strip():
        reasons.append("MISSING_CITATION_LOCATOR")
    review_status = payload.get("review_status")
    if review_status is None:
        reasons.append("MISSING_REVIEW_STATUS")
    elif review_status != policy.required_review_status:
        reasons.append("REVIEW_STATUS_INELIGIBLE")
    rights_status = payload.get("rights_status")
    if rights_status is None:
        reasons.append("MISSING_RIGHTS_STATUS")
    elif rights_status != policy.required_rights_status:
        reasons.append("RIGHTS_STATUS_INELIGIBLE")
    for field, target, reason in (
        ("population_scope", policy.target_population, "POPULATION_SCOPE_INCOMPATIBLE"),
        ("role_scope", policy.target_role, "ROLE_SCOPE_INCOMPATIBLE"),
        ("risk_scope", policy.risk_level, "RISK_SCOPE_INCOMPATIBLE"),
    ):
        scope = payload.get(field)
        if scope is None:
            if target is not None:
                reasons.append(f"MISSING_{field.upper()}")
        elif target is not None and target not in scope:
            reasons.append(reason)
    return EvidenceEligibility(eligible=not reasons, reason_codes=tuple(dict.fromkeys(reasons)))


def _chunk_payload(chunk: Any) -> tuple[dict[str, JsonValue], Mapping[str, Any]]:
    if isinstance(chunk, KnowledgeChunk):
        raw = cast(Mapping[str, Any], chunk.model_dump(mode="json"))
    elif hasattr(chunk, "model_dump"):
        value = chunk.model_dump(mode="json")
        if not isinstance(value, Mapping):
            raise EvidenceShapeError("retrieval chunk model_dump must be an object")
        raw = cast(Mapping[str, Any], value)
    elif isinstance(chunk, Mapping):
        raw = chunk
    else:
        raise EvidenceShapeError("retrieval chunk must be a KnowledgeChunk or object")

    payload: dict[str, JsonValue] = {}
    for field in sorted(_KNOWN_CHUNK_FIELDS):
        value = raw.get(field)
        if field in {
            "schema_version",
            "chunk_id",
            "document_id",
            "text",
            "content_type",
            "review_status",
            "rights_status",
            "content_hash",
        }:
            if value is _MISSING:
                value = None
            payload[field] = _copy_json(value)
        elif field in {"location", "citation", "embedding"}:
            payload[field] = _copy_json(value) if value is not None else None
        else:
            payload[field] = _copy_json(value) if value is not None else None

    observed = {
        key: _copy_json(value) for key, value in raw.items() if key not in _KNOWN_CHUNK_FIELDS
    }
    payload["observed"] = cast(JsonValue, _copy_json(observed))
    # Core identifiers are required to find/match evidence.  Other absent
    # contract fields remain explicit nulls and make the item ineligible.
    payload["chunk_id"] = _required_identifier(
        payload.get("chunk_id"), field="chunk_id", prefix="CHUNK_"
    )
    payload["document_id"] = _required_identifier(
        payload.get("document_id"), field="document_id", prefix="KB_"
    )
    text = payload.get("text")
    if text is not None and not isinstance(text, str):
        raise EvidenceShapeError("chunk text must be a string or null")
    citation = payload.get("citation")
    if citation is not None and not isinstance(citation, Mapping):
        raise EvidenceShapeError("chunk citation must be an object or null")
    return payload, observed


def build_retrieval_evidence_bundle(
    retrieval: RetrievalResult | Mapping[str, Any],
    *,
    transaction_id: str | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    policy: EligibilityPolicy | Mapping[str, Any] | None = None,
    strict_eligibility: bool = True,
) -> RetrievalEvidenceBundle:
    """Bind one observed RAG result into an immutable, hashed evidence bundle.

    ``strict_eligibility`` defaults to ``True`` for the generation boundary.
    Set it to ``False`` only for an audit/review path that must retain an
    ineligible observed response before explicitly calling
    :meth:`RetrievalEvidenceBundle.require_eligible`.
    """

    retrieval_id, chunks, label, trace = _retrieval_parts(retrieval)
    selected_policy = _policy(policy)
    normalized_trace = cast(dict[str, JsonValue], _copy_json(trace) if trace is not None else None)
    trace_mapping = trace
    linkage: dict[str, JsonValue] = {
        "transaction_id": _optional_string(transaction_id, field="transaction_id"),
        "request_id": _optional_string(request_id, field="request_id"),
        "trace_id": _optional_string(trace_id, field="trace_id"),
    }
    if linkage["request_id"] is None:
        linkage["request_id"] = _optional_string(
            _trace_field(trace_mapping, "request_id"), field="request_id"
        )
    if linkage["trace_id"] is None:
        linkage["trace_id"] = _optional_string(
            _trace_field(trace_mapping, "trace_id"), field="trace_id"
        )
    provenance: dict[str, JsonValue] = {
        "retrieval_id": retrieval_id,
        "label": label,
        "trace": normalized_trace,
    }
    for field in _PROVENANCE_FIELDS:
        provenance[field] = _copy_json(_trace_field(trace_mapping, field))
    # Retrieval identity is already a required observed field; no synthetic
    # index/corpus/build/snapshot/run identity is ever substituted here.

    frozen_items: list[RetrievalEvidence] = []
    for index, chunk in enumerate(chunks, start=1):
        payload, _observed = _chunk_payload(chunk)
        payload_for_id = {
            "retrieval_id": retrieval_id,
            "position": index,
            "chunk_id": payload["chunk_id"],
            "document_id": payload["document_id"],
            "content_hash": payload["content_hash"],
        }
        evidence_id = f"EVID_{_sha256(_canonical_json(payload_for_id))[:32]}"
        citation_id = f"S{index}"
        eligibility = _eligibility(payload, selected_policy)
        frozen_items.append(
            RetrievalEvidence(
                citation_id=citation_id,
                evidence_id=evidence_id,
                payload=_FrozenMapping(payload),
                eligibility=eligibility,
            )
        )

    frozen_linkage = _FrozenMapping(linkage)
    frozen_provenance = _FrozenMapping(provenance)
    frozen_policy = _FrozenMapping(selected_policy.to_dict())
    unbound = RetrievalEvidenceBundle(
        retrieval_id=retrieval_id,
        linkage=frozen_linkage,
        provenance=frozen_provenance,
        policy=frozen_policy,
        items=tuple(frozen_items),
        bundle_hash="",
    )
    bundle_hash = _sha256(unbound.canonical_json)
    bundle = RetrievalEvidenceBundle(
        retrieval_id=retrieval_id,
        linkage=frozen_linkage,
        provenance=frozen_provenance,
        policy=frozen_policy,
        items=tuple(frozen_items),
        bundle_hash=bundle_hash,
    )
    if strict_eligibility:
        bundle.require_eligible()
    return bundle


__all__ = [
    "BundleIntegrityError",
    "CitationBindingError",
    "CitationIntegrityError",
    "CitationMembershipError",
    "EligibilityPolicy",
    "EvidenceBindingError",
    "EvidenceEligibility",
    "EvidenceEligibilityError",
    "EvidenceShapeError",
    "OpaqueCitationReference",
    "RetrievalEvidence",
    "RetrievalEvidenceBundle",
    "build_retrieval_evidence_bundle",
]
