"""Generate fictional school-account CSV batches for an isolated scenario.

This tool creates roster fixtures only. It never calls the school API or a
database, writes no passwords, and does not copy or join research response
rows to account fields. The supplied SAPA held-out manifest is recorded as a
metadata-only research reference.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from typing import Sequence


CSV_HEADER = ("login_name", "display_name", "role")
MAX_CSV_BYTES = 500 * 1024
MAX_BATCH_ROWS = 100
DEFAULT_COUNT = 800
DEFAULT_CLASS_SIZE = 100
DEFAULT_SEED = 20261013
MAX_SCENARIO_STUDENTS = 10_000
_SCENARIO_ID = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")
_SAPA_POPULATION_BOUNDARY = (
    "Self-selected SAPA Project online respondents from the source collection period; "
    "not a school, high-school, university-representative, clinical, or diagnostic sample."
)
_TEMP_PREFIX = ".school-roster-"


class RosterScenarioError(ValueError):
    """A safe, fixed error for invalid scenario input or output state."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    output_dir: Path
    research_manifest: Path
    count: int = DEFAULT_COUNT
    class_size: int = DEFAULT_CLASS_SIZE
    seed: int = DEFAULT_SEED


@dataclass(frozen=True)
class ResearchReference:
    manifest_filename: str
    manifest_path: str
    manifest_sha256: str
    source_reference: str
    source_sha256: str
    source_license: str
    source_record_count: int
    response_column_count: int
    source_population: str
    evaluation_sha256: str
    evaluation_record_count: int
    calibration_record_count: int


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _strict_int(value: object, *, field: str, minimum: int, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        bound = f" between {minimum} and {maximum}" if maximum is not None else f" at least {minimum}"
        raise RosterScenarioError("invalid_parameter", f"{field} must be an integer{bound}")
    return value


def validate_spec(spec: ScenarioSpec) -> None:
    if not isinstance(spec.scenario_id, str) or not _SCENARIO_ID.fullmatch(spec.scenario_id):
        raise RosterScenarioError(
            "invalid_scenario_id",
            "scenario id must use 1-32 uppercase ASCII letters, digits, or underscores",
        )
    _strict_int(spec.count, field="count", minimum=1, maximum=MAX_SCENARIO_STUDENTS)
    _strict_int(spec.class_size, field="class size", minimum=1, maximum=MAX_BATCH_ROWS)
    _strict_int(spec.seed, field="seed", minimum=0)
    if not isinstance(spec.output_dir, Path) or not isinstance(spec.research_manifest, Path):
        raise RosterScenarioError("invalid_path", "output and research manifest must be filesystem paths")
    if not spec.research_manifest.is_file():
        raise RosterScenarioError("research_manifest_missing", "held-out research manifest is unavailable")


def load_research_reference(path: Path) -> ResearchReference:
    """Read only the response-only import manifest, never response rows."""

    try:
        raw = path.read_bytes()
        manifest = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RosterScenarioError("research_manifest_invalid", "held-out research manifest could not be read") from exc
    if not isinstance(manifest, dict):
        raise RosterScenarioError("research_manifest_invalid", "held-out research manifest must be a JSON object")

    source = manifest.get("source")
    sampling = manifest.get("sampling")
    integrity = manifest.get("output_integrity")
    if not isinstance(source, dict) or not isinstance(sampling, dict) or not isinstance(integrity, dict):
        raise RosterScenarioError("research_manifest_invalid", "held-out research manifest is missing required metadata")
    evaluation = integrity.get("evaluation.csv")
    columns = manifest.get("response_columns")
    if not isinstance(evaluation, dict) or not isinstance(columns, list):
        raise RosterScenarioError("research_manifest_invalid", "held-out response metadata is incomplete")

    if manifest.get("format_version") != "research-response.v1" or manifest.get("research_only") is not True:
        raise RosterScenarioError("research_manifest_invalid", "source is not a research-only response manifest")
    if manifest.get("publication_status") != "not_approved_for_publication_or_operational_use":
        raise RosterScenarioError("research_manifest_invalid", "source publication boundary is missing")
    if manifest.get("psychological_interpretation_allowed") is not False:
        raise RosterScenarioError("research_manifest_invalid", "source interpretation boundary is missing")
    not_created = manifest.get("not_created")
    if not isinstance(not_created, dict) or not_created.get("scores_or_interpretations") is not True:
        raise RosterScenarioError("research_manifest_invalid", "source must not contain scores or interpretations")

    source_reference = source.get("reference")
    source_sha256 = source.get("sha256")
    source_license = source.get("license")
    source_population = source.get("population")
    source_record_count = sampling.get("source_record_count")
    calibration_record_count = sampling.get("calibration_record_count")
    evaluation_record_count = sampling.get("evaluation_record_count")
    selected_record_count = sampling.get("selected_record_count")
    evaluation_sha256 = evaluation.get("sha256")
    if (
        not isinstance(source_reference, str)
        or "10.7910/DVN/C40K1U" not in source_reference
        or not isinstance(source_sha256, str)
        or not _SHA256.fullmatch(source_sha256)
        or source_license != "CC0-1.0"
        or source_population != _SAPA_POPULATION_BOUNDARY
        or type(source_record_count) is not int
        or source_record_count != 128_464
        or type(calibration_record_count) is not int
        or calibration_record_count != 10_000
        or type(evaluation_record_count) is not int
        or evaluation_record_count != 800
        or type(selected_record_count) is not int
        or selected_record_count != calibration_record_count + evaluation_record_count
        or type(sampling.get("source_row_identifiers_written")) is not bool
        or sampling["source_row_identifiers_written"] is not False
        or sampling.get("splits_disjoint") is not True
        or len(columns) != 99
        or not all(isinstance(column, str) and column for column in columns)
        or len(set(columns)) != len(columns)
        or type(evaluation.get("record_count")) is not int
        or evaluation["record_count"] != 800
        or not isinstance(evaluation_sha256, str)
        or not _SHA256.fullmatch(evaluation_sha256)
    ):
        raise RosterScenarioError(
            "research_manifest_boundary_mismatch",
            "manifest does not match the approved-metadata boundary for the SAPA held-out split",
        )

    return ResearchReference(
        manifest_filename=path.name,
        manifest_path=str(path.resolve()),
        manifest_sha256=_sha256_bytes(raw),
        source_reference=source_reference,
        source_sha256=source_sha256.casefold(),
        source_license=source_license,
        source_record_count=source_record_count,
        response_column_count=len(columns),
        source_population=source_population,
        evaluation_sha256=evaluation_sha256.casefold(),
        evaluation_record_count=evaluation_record_count,
        calibration_record_count=calibration_record_count,
    )


def _csv_bytes(scenario_slug: str, student_numbers: Sequence[int]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for student_number in student_numbers:
        login_name = f"SYNTHETIC_{scenario_slug}_STUDENT_{student_number:06d}"
        display_name = f"合成学生-{student_number:06d}"
        writer.writerow((login_name, display_name, "student"))
    encoded = stream.getvalue().encode("utf-8")
    if len(student_numbers) > MAX_BATCH_ROWS or len(encoded) > MAX_CSV_BYTES:
        raise RosterScenarioError("batch_limit_exceeded", "generated CSV exceeds the school import batch limit")
    return encoded


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _cleanup_temporary_directory(temporary_dir: Path, output_parent: Path) -> None:
    try:
        info = temporary_dir.lstat()
        expected_parent = output_parent.resolve(strict=True)
        actual_parent = temporary_dir.parent.resolve(strict=True)
        resolved_temp = temporary_dir.resolve(strict=True)
    except FileNotFoundError:
        return
    except (OSError, RuntimeError) as exc:
        raise RosterScenarioError("cleanup_failed", "temporary roster output could not be verified") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        not temporary_dir.name.startswith(_TEMP_PREFIX)
        or actual_parent != expected_parent
        or resolved_temp.parent != expected_parent
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or bool(getattr(info, "st_file_attributes", 0) & reparse_flag)
    ):
        raise RosterScenarioError("cleanup_failed", "refusing cleanup outside the owned temporary output directory")
    try:
        shutil.rmtree(temporary_dir)
    except OSError as exc:
        raise RosterScenarioError("cleanup_failed", "owned temporary roster output could not be removed") from exc


def generate_roster(spec: ScenarioSpec) -> dict[str, object]:
    """Generate fictional account CSV batches and a metadata-only manifest."""

    validate_spec(spec)
    research = load_research_reference(spec.research_manifest)
    destination = spec.output_dir
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise RosterScenarioError("output_path_invalid", "output path could not be inspected") from exc
    else:
        raise RosterScenarioError("output_exists", "output directory already exists; choose a new destination")

    scenario_slug = spec.scenario_id
    school_label = f"合成学校-{scenario_slug}"
    class_count = (spec.count + spec.class_size - 1) // spec.class_size
    student_numbers = list(range(1, spec.count + 1))
    random.Random(spec.seed).shuffle(student_numbers)
    output_parent = destination.parent
    try:
        temporary_dir = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX, dir=output_parent))
    except OSError as exc:
        raise RosterScenarioError("output_write_failed", "output parent is unavailable") from exc

    batches: list[dict[str, object]] = []
    try:
        for index in range(class_count):
            class_number = index + 1
            start = index * spec.class_size
            class_students = sorted(student_numbers[start : start + spec.class_size])
            filename = f"class_{class_number:03d}.csv"
            content = _csv_bytes(scenario_slug, class_students)
            (temporary_dir / filename).write_bytes(content)
            batches.append(
                {
                    "batch_number": class_number,
                    "class_label": f"{school_label}-{class_number:02d}班",
                    "class_ref": None,
                    "csv_file": filename,
                    "row_count": len(class_students),
                    "sha256": _sha256_bytes(content),
                    "size_bytes": len(content),
                    "class_must_be_created_or_selected_before_import": True,
                }
            )

        manifest: dict[str, object] = {
            "format_version": "fictional-school-roster.v1",
            "scenario": {
                "scenario_id": spec.scenario_id,
                "fictional": True,
                "school_label": school_label,
                "grade_label": "合成高中年级（虚构）",
                "student_count": spec.count,
                "class_size": spec.class_size,
                "class_count": class_count,
                "seed": spec.seed,
                "population_scope": "fictional school-account import workflow fixture only",
            },
            "account_import_contract": {
                "csv_header": list(CSV_HEADER),
                "role": "student",
                "maximum_rows_per_batch": MAX_BATCH_ROWS,
                "maximum_csv_bytes": MAX_CSV_BYTES,
                "password_column_present": False,
                "class_assignment_is_selected_separately_in_school_directory": True,
                "each_csv_matches_exact_frontend_header": True,
            },
            "class_batches": batches,
            "research_reference": {
                "kind": "heldout_research_index_metadata_only",
                "manifest_filename": research.manifest_filename,
                "manifest_path": research.manifest_path,
                "manifest_sha256": research.manifest_sha256,
                "source_reference": research.source_reference,
                "source_sha256": research.source_sha256,
                "source_license": research.source_license,
                "source_population_boundary": research.source_population,
                "source_record_count": research.source_record_count,
                "source_response_column_count": research.response_column_count,
                "calibration_record_count": research.calibration_record_count,
                "evaluation_file": "evaluation.csv",
                "evaluation_sha256": research.evaluation_sha256,
                "evaluation_record_count": research.evaluation_record_count,
                "used_to_generate_accounts": False,
                "response_rows_copied_to_roster": False,
                "account_to_response_row_mapping_created": False,
                "source_population_relabelled": False,
            },
            "execution_boundary": {
                "scenario_generation_only": True,
                "database_writes_performed": False,
                "api_writes_performed": False,
                "accounts_imported": False,
                "passwords_or_credentials_written": False,
                "online_cat_or_item_parameters_changed": False,
                "professional_review_or_school_population_approval_claimed": False,
            },
            "next_acceptance_steps": [
                f"学校目录页面只支持查看/改名现有班级，不提供建校或建班；须先由 Controller 使用已授权的学校/班级配置流程准备 {len(batches)} 个虚构班级。",
                "逐批在学校目录页面选择一个已存在的对应 class_ref；CSV 每批不超过 100 行且只含规定的三列。",
                "每批先执行服务端预览，确认 row_count 与错误列表后，再由 Controller 单独决定是否整批导入。",
                "导入后核对每批 batch_ref、created_count、待激活状态、班级归属和审计记录。",
                "账号激活密码通过既有单独流程设置；不得将密码写回本场景 CSV 或 manifest。",
                f"使用真实 API 与浏览器完成 {len(batches)} 批验收；本生成器没有执行该流程。",
            ],
        }
        _write_json(temporary_dir / "manifest.json", manifest)
        try:
            os.rename(temporary_dir, destination)
        except OSError as exc:
            raise RosterScenarioError("output_publish_failed", "new scenario output could not be finalized") from exc
    except Exception:
        if temporary_dir.exists():
            _cleanup_temporary_directory(temporary_dir, output_parent)
        raise

    return {
        "status": "ok",
        "scenario_id": spec.scenario_id,
        "fictional": True,
        "student_count": spec.count,
        "class_count": class_count,
        "batch_count": len(batches),
        "manifest_file": "manifest.json",
        "output_files": [batch["csv_file"] for batch in batches] + ["manifest.json"],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate fictional school-account CSV batches; does not import accounts or copy response rows."
    )
    parser.add_argument("--scenario-id", required=True, help="Explicit fictional scenario ID")
    parser.add_argument("--output-dir", required=True, type=Path, help="New output directory; existing paths are refused")
    parser.add_argument("--research-manifest", required=True, type=Path, help="SAPA 10,000/800 response-only manifest")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help=f"Fictional student count (default {DEFAULT_COUNT})")
    parser.add_argument("--class-size", type=int, default=DEFAULT_CLASS_SIZE, help=f"Students per fictional class/batch (maximum {MAX_BATCH_ROWS})")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Reproducible class allocation seed")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = generate_roster(
            ScenarioSpec(
                scenario_id=args.scenario_id,
                output_dir=args.output_dir,
                research_manifest=args.research_manifest,
                count=args.count,
                class_size=args.class_size,
                seed=args.seed,
            )
        )
    except RosterScenarioError as exc:
        print(json.dumps({"status": "error", "code": exc.code, "message": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
