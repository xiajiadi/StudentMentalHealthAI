"""Build isolated, pending-review Markdown packages from approved research staging metadata.

This adapter only prepares source documents for later human review. It does not
run the publication pipeline, write an index, or mark content as human curated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
from typing import Any

import yaml

from .config import PipelineConfig
from .domain.source import SourceRecord, SourceRequest
from .parsers.markdown_parser import MarkdownCuratedParser


_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_YEAR_PREFIX = re.compile(r"^\s*(19\d{2}|20\d{2}|21\d{2})\b")
_REQUIRED_EXCERPT_FIELDS = (
    "title",
    "canonical_url",
    "publisher",
    "version_date",
    "layer",
    "license",
    "license_url",
    "license_evidence",
    "text_scope",
    "stage_modifications",
    "required_attribution",
    "stage_retrieved_date_utc",
    "stage_retrieval_method",
    "stage_file",
    "stage_sha256",
)
_CATEGORY_BY_LAYER = {
    "policy": "policy",
    "theory": "theory",
    "intervention": "practice_guidance",
}


class ResearchStagingError(ValueError):
    """Fail-closed research staging input or output error."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _required_text(record: dict[str, Any], name: str, *, record_id: str) -> str:
    value = record.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ResearchStagingError(f"{record_id}: required metadata is missing: {name}")
    return value.strip()


def _no_reparse_components(root: Path, target: Path) -> bool:
    try:
        relative = target.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current = current / part
        try:
            attributes = current.stat(follow_symlinks=False).st_file_attributes
        except (AttributeError, OSError):
            attributes = 0
        if current.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            return False
    return True


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        attributes = 0
    return path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _absolute_output_path_without_reparse_points(output_dir: Path) -> Path:
    requested = Path(output_dir).expanduser()
    absolute = Path(os.path.abspath(requested))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if os.path.lexists(current) and _is_reparse_point(current):
            raise ResearchStagingError("output path contains an existing symlink or reparse-point component")
    return absolute


def _resolve_source_path(staging_root: Path, stage_file: str, *, record_id: str) -> Path:
    if not isinstance(stage_file, str) or not stage_file.strip():
        raise ResearchStagingError(f"{record_id}: stage_file is required")
    windows_path = PureWindowsPath(stage_file)
    posix_path = PurePosixPath(stage_file.replace("\\", "/"))
    if windows_path.is_absolute() or windows_path.drive or posix_path.is_absolute() or ".." in posix_path.parts:
        raise ResearchStagingError(f"{record_id}: stage_file escapes the declared staging root")
    if any(part in {"", "."} for part in posix_path.parts):
        raise ResearchStagingError(f"{record_id}: stage_file path is invalid")
    target = staging_root.joinpath(*posix_path.parts)
    if not _no_reparse_components(staging_root, target.absolute()):
        raise ResearchStagingError(f"{record_id}: staged source path traverses a reparse point")
    try:
        resolved = target.resolve(strict=True)
    except OSError as exc:
        raise ResearchStagingError(f"{record_id}: staged source file is unavailable") from exc
    if not _no_reparse_components(staging_root, resolved) or not resolved.is_file():
        raise ResearchStagingError(f"{record_id}: staged source file is outside the root or is a reparse point")
    return resolved


def _source_population(record: dict[str, Any], *, record_id: str) -> str:
    population = record.get("source_population", record.get("population"))
    if not isinstance(population, str) or not population.strip():
        raise ResearchStagingError(f"{record_id}: source population metadata is missing")
    return population.strip()


def _front_matter(record: dict[str, Any], *, language: str, record_id: str) -> dict[str, Any]:
    for name in _REQUIRED_EXCERPT_FIELDS:
        _required_text(record, name, record_id=record_id)
    if record.get("rights_status") != "verified":
        raise ResearchStagingError(f"{record_id}: staged excerpt rights are not verified")
    if record.get("review_status") != "pending_human_review":
        raise ResearchStagingError(f"{record_id}: excerpt is not explicitly pending human review")
    if record.get("human_curated") is not False:
        raise ResearchStagingError(f"{record_id}: excerpt must remain human_curated=false")
    if record.get("publication_eligible") is not False:
        raise ResearchStagingError(f"{record_id}: excerpt must remain publication_eligible=false")
    if record.get("stage_recommendation") != "text_only_staged_pending_content_review":
        raise ResearchStagingError(f"{record_id}: excerpt staging recommendation is not approved for text-only staging")
    layer = _required_text(record, "layer", record_id=record_id)
    if layer not in _CATEGORY_BY_LAYER:
        raise ResearchStagingError(f"{record_id}: unsupported research layer")
    population = _source_population(record, record_id=record_id)
    version_date = _required_text(record, "version_date", record_id=record_id)
    year_match = _YEAR_PREFIX.match(version_date)
    if not year_match:
        raise ResearchStagingError(f"{record_id}: version date does not contain a declared publication year")
    attribution = _required_text(record, "required_attribution", record_id=record_id)
    return {
        "title": _required_text(record, "title", record_id=record_id),
        "organization": _required_text(record, "publisher", record_id=record_id),
        "author": record.get("author"),
        "published_year": int(year_match.group(1)),
        "language": language,
        "population_scope": [population],
        "category": _CATEGORY_BY_LAYER[layer],
        "rights_status": "verified",
        # knowledge.v1's frozen enum is pending/approved/rejected. ReviewGate maps
        # this unapproved value to the explicit pending_review decision.
        "review_status": "pending",
        # Empty scopes intentionally fail closed until a human reviewer assigns them.
        "role_scope": [],
        "risk_scope": [],
        "topic": record.get("topic"),
        "authority_level": None,
        "source_url": _required_text(record, "canonical_url", record_id=record_id),
        "human_curated": False,
        "source_type": "other",
        "publication_eligible": False,
        "review_decision": "pending_review",
        "staging_status": "pending_review_not_indexed",
        "research_layer": layer,
        "version_date": version_date,
        "source_license": _required_text(record, "license", record_id=record_id),
        "license_url": _required_text(record, "license_url", record_id=record_id),
        "license_evidence": _required_text(record, "license_evidence", record_id=record_id),
        "text_scope": _required_text(record, "text_scope", record_id=record_id),
        "source_population": population,
        "stage_modifications": _required_text(record, "stage_modifications", record_id=record_id),
        "required_attribution": attribution,
        "stage_retrieved_date_utc": _required_text(record, "stage_retrieved_date_utc", record_id=record_id),
        "stage_retrieval_method": _required_text(record, "stage_retrieval_method", record_id=record_id),
        "stage_recommendation": record["stage_recommendation"],
        "source_stage_file": _required_text(record, "stage_file", record_id=record_id),
        "source_stage_sha256": _required_text(record, "stage_sha256", record_id=record_id).casefold(),
        "language_basis": "explicit language argument supplied by the adapter caller; source candidate has no per-record language field",
    }


def _metadata_only_summary(record: dict[str, Any], *, record_id: str) -> dict[str, Any]:
    title = _required_text(record, "title", record_id=record_id)
    url = _required_text(record, "canonical_url", record_id=record_id)
    recommendation = _required_text(record, "stage_recommendation", record_id=record_id)
    publisher = record.get("publisher")
    license_name = record.get("license")
    return {
        "candidate_id": record_id,
        "title": title,
        "source_url": url,
        "publisher": publisher if isinstance(publisher, str) else None,
        "rights_status": record.get("rights_status", "unknown"),
        "review_status": "pending_review",
        "candidate_summary": recommendation,
        "source_stage_file_present": False,
        "body_created": False,
        "license_metadata": license_name if isinstance(license_name, str) else None,
    }


def stage_research_sources(
    source_manifest_path: Path,
    output_dir: Path,
    *,
    language: str,
) -> dict[str, Any]:
    """Create an isolated pending-review package from rights-verified staged excerpts.

    Metadata-only candidates remain metadata-only. The caller must choose a
    language explicitly because source records do not provide per-record language.
    """
    manifest_input = Path(source_manifest_path).expanduser().absolute()
    if manifest_input.is_symlink():
        raise ResearchStagingError("source candidate manifest cannot be a symlink")
    if _is_reparse_point(manifest_input):
        raise ResearchStagingError("source candidate manifest cannot be a reparse point")
    manifest_path = manifest_input.resolve(strict=True)
    output_path = _absolute_output_path_without_reparse_points(Path(output_dir)).resolve(strict=False)
    if not isinstance(language, str) or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", language.strip()):
        raise ResearchStagingError("an explicit language tag is required")
    language = language.strip()
    try:
        source_manifest_bytes = manifest_path.read_bytes()
        source_manifest_sha256 = _sha256_bytes(source_manifest_bytes)
        manifest = json.loads(source_manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchStagingError("source candidate manifest is unavailable or invalid") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("records"), list):
        raise ResearchStagingError("source candidate manifest schema is invalid")
    if manifest.get("live_corpus_changed") is not False:
        raise ResearchStagingError("source candidate manifest does not confirm an unchanged live corpus")
    declared_root = manifest.get("staging_root")
    if not isinstance(declared_root, str) or not declared_root.strip():
        raise ResearchStagingError("source staging root is missing")
    declared_root_path = Path(declared_root).expanduser()
    if not declared_root_path.is_absolute() or declared_root_path.is_symlink():
        raise ResearchStagingError("declared staging root must be an absolute non-symlink directory")
    staging_root = declared_root_path.resolve(strict=True)
    if (
        not staging_root.is_dir()
        or manifest_input.parent != declared_root_path.absolute()
        or manifest_path.parent != staging_root
    ):
        raise ResearchStagingError("candidate manifest must be directly inside its declared staging root")
    if not _no_reparse_components(Path(staging_root.anchor), staging_root):
        raise ResearchStagingError("declared staging root is a reparse point")
    try:
        output_path.relative_to(staging_root)
    except ValueError:
        pass
    else:
        raise ResearchStagingError("output directory must be isolated outside the original staging root")
    if os.path.lexists(output_path):
        raise ResearchStagingError("output directory already exists; refusing to overwrite")

    records = manifest["records"]
    if not records:
        raise ResearchStagingError("source candidate manifest contains no records")
    ids: set[str] = set()
    stage_paths: set[Path] = set()
    prepared: list[tuple[dict[str, Any], Path, bytes, dict[str, Any]]] = []
    metadata_only: list[dict[str, Any]] = []
    for raw_record in records:
        if not isinstance(raw_record, dict):
            raise ResearchStagingError("candidate record must be an object")
        record_id = raw_record.get("id")
        if not isinstance(record_id, str) or not _ID_PATTERN.fullmatch(record_id):
            raise ResearchStagingError("candidate id is missing or invalid")
        if record_id in ids:
            raise ResearchStagingError(f"duplicate candidate id: {record_id}")
        ids.add(record_id)
        stage_file = raw_record.get("stage_file")
        if stage_file is None or stage_file == "":
            if raw_record.get("stage_sha256") not in (None, ""):
                raise ResearchStagingError(f"{record_id}: metadata-only candidate cannot declare an unmaterialized stage hash")
            metadata_only.append(_metadata_only_summary(raw_record, record_id=record_id))
            continue

        front = _front_matter(raw_record, language=language, record_id=record_id)
        declared_hash = front["source_stage_sha256"]
        if not _SHA256_PATTERN.fullmatch(declared_hash):
            raise ResearchStagingError(f"{record_id}: declared source hash is invalid")
        source_path = _resolve_source_path(staging_root, stage_file, record_id=record_id)
        if source_path in stage_paths:
            raise ResearchStagingError(f"{record_id}: staged source path is reused by another candidate")
        stage_paths.add(source_path)
        original = source_path.read_bytes()
        if _sha256_bytes(original) != declared_hash:
            raise ResearchStagingError(f"{record_id}: staged source hash does not match the manifest")
        try:
            original.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResearchStagingError(f"{record_id}: staged Markdown is not valid UTF-8") from exc
        yaml_header = yaml.safe_dump(front, allow_unicode=True, sort_keys=False).encode("utf-8")
        packaged = b"---\n" + yaml_header + b"---\n" + original
        prepared.append((raw_record, source_path, packaged, front))

    if not prepared:
        raise ResearchStagingError("no rights-verified staged excerpt is eligible for a pending-review package")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.mkdir(parents=False, exist_ok=False)
    config = PipelineConfig(default_language=language, publish_only_approved=True, allow_test_auto_approve=False)
    parser = MarkdownCuratedParser()
    documents: list[dict[str, Any]] = []
    try:
        for record, source_path, packaged, front in prepared:
            record_id = str(record["id"])
            filename = f"{record_id}.md"
            target = output_path / filename
            target.write_bytes(packaged)
            source_record = SourceRecord.from_request(
                SourceRequest(
                    path=target,
                    input_mode="raw",
                    metadata={"source_type": front["source_type"]},
                )
            )
            document = parser.parse(source_record, config)
            if (
                document.metadata.human_curated is not False
                or document.metadata.rights_status != "verified"
                or document.metadata.review_status != "pending"
                or document.metadata.extra.get("publication_eligible") is not False
            ):
                raise ResearchStagingError(f"{record_id}: parsed metadata did not preserve pending-review restrictions")
            documents.append(
                {
                    "candidate_id": record_id,
                    "document_id": document.document_id,
                    "title": document.title,
                    "source_file": filename,
                    "source_file_sha256": _sha256_file(target),
                    "original_stage_file": source_path.name,
                    "original_stage_sha256": front["source_stage_sha256"],
                    "document_content_hash": document.content_hash,
                    "parser": document.parser,
                    "parser_version": document.parser_version,
                    "pipeline_version": document.pipeline_version,
                    "language": document.language,
                    "population_scope": document.metadata.population_scope,
                    "category": document.metadata.category,
                    "rights_status": document.metadata.rights_status,
                    "review_status": document.metadata.review_status,
                    "review_decision": "pending_review",
                    "human_curated": document.metadata.human_curated,
                    "publication_eligible": document.metadata.extra.get("publication_eligible"),
                    "role_scope": document.metadata.role_scope,
                    "risk_scope": document.metadata.risk_scope,
                    "source_url": document.metadata.source_url,
                    "source_license": document.metadata.extra.get("source_license"),
                    "license_evidence": document.metadata.extra.get("license_evidence"),
                    "stage_modifications": document.metadata.extra.get("stage_modifications"),
                    "text_scope": document.metadata.extra.get("text_scope"),
                    "required_attribution": document.metadata.extra.get("required_attribution"),
                    "staging_status": "pending_review_not_indexed",
                    "body_preserved_byte_for_byte": True,
                }
            )
    except Exception:
        # The destination is new and private to this invocation; preserve it for
        # inspection on failure instead of deleting any path recursively.
        raise

    output_manifest = {
        "schema_version": "research-knowledge-staging.v1",
        "status": "pending_review",
        "publication_eligible": False,
        "human_curated": False,
        "indexed": False,
        "live_corpus_changed": False,
        "source_candidate_manifest": str(manifest_path),
        "source_candidate_manifest_sha256": source_manifest_sha256,
        "source_staging_root": str(staging_root),
        "caller_language": language,
        "language_basis": "explicit adapter argument; source candidates omit per-record language",
        "contract_release": config.contract_release,
        "pipeline_version": config.pipeline_version,
        "markdown_parser": {"name": parser.name, "version": parser.version},
        "source_documents": documents,
        "metadata_only_candidates": metadata_only,
        "metadata_only_candidate_count": len(metadata_only),
        "staged_excerpt_count": len(documents),
        "all_source_population_scopes_preserved": True,
        "no_summary_body_created": True,
        "publication_gate": {
            "review_state": "pending_review",
            "decision": "human review required",
            "auto_approval": False,
            "live_index_write": False,
        },
    }
    if _sha256_file(manifest_path) != source_manifest_sha256:
        raise ResearchStagingError("source candidate manifest changed while the package was being built")
    manifest_bytes = (json.dumps(output_manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    (output_path / "manifest.json").write_bytes(manifest_bytes)
    result = {
        "status": "pending_review",
        "output_dir": str(output_path),
        "staged_excerpt_count": len(documents),
        "metadata_only_candidate_count": len(metadata_only),
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "publication_eligible": False,
        "human_curated": False,
        "indexed": False,
    }
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage rights-verified research Markdown for human review only.")
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--language", required=True, help="Explicit BCP-47 language tag; source records omit this field.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = stage_research_sources(args.source_manifest, args.output_dir, language=args.language)
    except ResearchStagingError as exc:
        print(f"research_staging_failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
