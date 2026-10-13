"""Aggregate-only CAT research replay for the isolated SAPA/IPIP99 artifacts.

This module uses the public ``adaptivetesting`` item, selection, EAP, and GRM
response-generation interfaces directly. It does not construct an online
``ItemBank`` or ``Session`` and does not modify the runtime publication gate.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import sys
import tempfile
from typing import Iterable, Mapping, Sequence

import adaptivetesting as adt

from cat_engine.domain.config import CATConfig


FORMAT_VERSION = "empirical-cat-research.v1"
RUN_FORMAT_VERSION = "empirical-cat-run.v2"
CHECKPOINT_FORMAT_VERSION = "empirical-cat-domain-checkpoint.v1"
EXPECTED_SOURCE_SHA256 = "4c151783eb5c8cbe125b91dfad425c08fa04015af9d52dca543fb2a8a8b9f4f9"
EXPECTED_DOMAINS = (
    "Agreeableness",
    "Conscientiousness",
    "Emotional Stability",
    "Extraversion",
    "Intellect / Imagination",
)
DOMAIN_FILES = {
    "Agreeableness": ("domains-20261014-final", "Agreeableness.json"),
    "Conscientiousness": ("domains-20261014-final", "Conscientiousness.json"),
    "Emotional Stability": ("domains-20261014-final", "Emotional-Stability.json"),
    "Extraversion": ("", "mirt-extraversion.json"),
    "Intellect / Imagination": ("domains-20261014-final", "Intellect-Imagination.json"),
}
CATEGORY_LABELS = {
    1: "Very Inaccurate",
    2: "Moderately Inaccurate",
    3: "Slightly Inaccurate",
    4: "Slightly Accurate",
    5: "Moderately Accurate",
    6: "Very Accurate",
}
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,100}$")


class ResearchReplayError(ValueError):
    """A fail-closed input or simulation error with no response-value echo."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResearchItem:
    qid: str
    key_direction: str
    a: float
    thresholds: tuple[float, ...]


@dataclass(frozen=True)
class ResearchDomain:
    name: str
    items: tuple[ResearchItem, ...]
    fit_sha256: str
    fit_model: Mapping[str, object]
    fit_iterations: int
    fit_warnings: tuple[str, ...]


@dataclass(frozen=True)
class ResearchInputs:
    root: Path
    response_dir: Path
    calibration_sha256: str
    evaluation_sha256: str
    source_sha256: str
    source_reference: str
    source_license: str
    source_population: str
    response_columns: tuple[str, ...]
    response_manifest_sha256: str
    crosswalk_sha256: str
    batch_manifest_sha256: str
    probability_parity: Mapping[str, object]
    domains: tuple[ResearchDomain, ...]


@dataclass(frozen=True)
class ResearchCATConfig:
    envelope: Mapping[str, object]
    cat: CATConfig
    file_sha256: str
    content_sha256: str


@dataclass
class _EngineRun:
    engine: object
    items_by_qid: dict[str, object]
    research_items_by_qid: dict[str, ResearchItem]
    theta: float
    se: float
    answered: int = 0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def score_source_response(raw_response: int, key_direction: str) -> int:
    """Map SAPA raw 1..6 to the provider's keyed category index 0..5."""

    if type(raw_response) is not int or raw_response not in CATEGORY_LABELS:
        raise ResearchReplayError("invalid_source_category", "source response is outside ordinal categories 1..6")
    if key_direction == "positive":
        return raw_response - 1
    if key_direction == "reverse":
        return 6 - raw_response
    raise ResearchReplayError("invalid_key_direction", "item key direction must be positive or reverse")


def _logistic(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1.0 / (1.0 + inverse)
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def _grm_category_probabilities(theta: float, item: ResearchItem) -> tuple[float, ...]:
    """Six-category mirt graded probabilities in the library's logistic link."""

    cumulative = (1.0,) + tuple(_logistic(item.a * (theta - value)) for value in item.thresholds) + (0.0,)
    probabilities = tuple(cumulative[index] - cumulative[index + 1] for index in range(6))
    if any(not math.isfinite(value) or value < 0.0 for value in probabilities):
        raise ResearchReplayError("probability_parity_invalid", "GRM category probabilities are not finite and non-negative")
    return probabilities


def _manual_eap_moments(item: ResearchItem, response_score: int) -> tuple[float, float]:
    """Independent numeric likelihood check used only by the parity gate."""

    numerator = denominator = second_moment = 0.0
    steps = 4000
    for index in range(steps + 1):
        theta = -4.0 + 8.0 * index / steps
        probability = _grm_category_probabilities(theta, item)[response_score]
        weight = math.exp(-0.5 * theta * theta) * probability
        if index in {0, steps}:
            weight *= 0.5
        denominator += weight
        numerator += theta * weight
        second_moment += theta * theta * weight
    if not math.isfinite(denominator) or denominator <= 0:
        raise ResearchReplayError("probability_parity_invalid", "manual GRM likelihood check has zero posterior mass")
    mean = numerator / denominator
    variance = max(0.0, second_moment / denominator - mean * mean)
    return mean, math.sqrt(variance)


def _verify_probability_parity(domains: Sequence[ResearchDomain]) -> dict[str, object]:
    """Verify logistic-link source and compare public EAP likelihood to mirt math."""

    package_version = importlib.metadata.version("adaptivetesting")
    if package_version != "1.2.1":
        raise ResearchReplayError("adaptivetesting_version_mismatch", "probability parity is verified only for adaptivetesting 1.2.1")
    package_root = Path(adt.__file__).resolve().parent
    grm_path = package_root / "math" / "estimators" / "__functions" / "__poly" / "__grm.py"
    eap_path = Path(inspect.getsourcefile(adt.ExpectedAPosteriori) or "")
    generator_path = package_root / "math" / "__gen_response_pattern.py"
    if not grm_path.is_file() or not eap_path.is_file() or not generator_path.is_file():
        raise ResearchReplayError("adaptivetesting_source_missing", "pinned adaptivetesting source needed for parity evidence is unavailable")
    try:
        grm_source = re.sub(r"\s+", " ", grm_path.read_text(encoding="utf-8"))
        eap_source = eap_path.read_text(encoding="utf-8")
        generator_source = re.sub(r"\s+", " ", generator_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ResearchReplayError("adaptivetesting_source_unreadable", "pinned adaptivetesting source cannot be read for parity evidence") from exc
    required_grm_fragments = (
        "1 / (1 + np.exp(-a * (theta - thresholds[k - 1])))",
        "1 / (1 + np.exp(-a * (theta - thresholds[k])))",
        "prob_k = p_ge_k - p_ge_k_plus_1",
    )
    if any(fragment not in grm_source for fragment in required_grm_fragments) or "GRM" not in eap_source:
        raise ResearchReplayError("adaptivetesting_link_mismatch", "installed GRM/EAP source does not match the verified logistic graded link")

    theta_grid = tuple(-4.0 + index * 0.5 for index in range(17))
    probability_vector_count = 0
    maximum_probability_sum_error = 0.0
    for domain in domains:
        for item in domain.items:
            for theta in theta_grid:
                probabilities = _grm_category_probabilities(theta, item)
                maximum_probability_sum_error = max(maximum_probability_sum_error, abs(sum(probabilities) - 1.0))
                probability_vector_count += 1
    if maximum_probability_sum_error > 1e-12:
        raise ResearchReplayError("probability_normalization_failed", "mirt GRM category probabilities do not sum to one")

    maximum_eap_mean_difference = 0.0
    maximum_eap_se_difference = 0.0
    likelihood_cases = 0
    for domain in domains:
        item = domain.items[len(domain.items) // 2]
        engine_item = adt.TestItem()
        engine_item.id = 0
        engine_item.a = item.a
        engine_item.b = list(item.thresholds)
        for score in range(6):
            try:
                estimator = adt.ExpectedAPosteriori(
                    [score],
                    [engine_item],
                    prior=adt.NormalPrior(0.0, 1.0),
                    optimization_interval=(-4.0, 4.0),
                    model="GRM",
                )
                package_mean = float(estimator.get_estimation())
                package_se = float(estimator.get_standard_error(package_mean))
            except Exception as exc:
                raise ResearchReplayError("adaptivetesting_likelihood_check_failed", "public EAP likelihood check failed") from exc
            manual_mean, manual_se = _manual_eap_moments(item, score)
            maximum_eap_mean_difference = max(maximum_eap_mean_difference, abs(package_mean - manual_mean))
            maximum_eap_se_difference = max(maximum_eap_se_difference, abs(package_se - manual_se))
            likelihood_cases += 1
    if maximum_eap_mean_difference > 1e-3 or maximum_eap_se_difference > 1e-3:
        raise ResearchReplayError("adaptivetesting_likelihood_mismatch", "public EAP posterior differs from the declared mirt GRM likelihood")

    generator_uses_softmax = "probabilities = softmax(np.array(log_probabilities))" in generator_source
    if not generator_uses_softmax:
        raise ResearchReplayError("adaptivetesting_generator_source_changed", "response generator source changed; review categorical sampling compatibility")
    return {
        "status": "source_and_public_eap_likelihood_parity_passed",
        "verified_package": "adaptivetesting==1.2.1",
        "link": "P(Y>=k)=logistic(a*(theta-b_k)); category probabilities are adjacent cumulative differences",
        "slope_scale": 1.0,
        "source_category_count": 6,
        "provider_score_indexes": [0, 1, 2, 3, 4, 5],
        "theta_grid": list(theta_grid),
        "all_item_probability_vectors_checked": probability_vector_count,
        "maximum_probability_sum_error": maximum_probability_sum_error,
        "public_eap_likelihood_cases": likelihood_cases,
        "maximum_eap_mean_difference": maximum_eap_mean_difference,
        "maximum_eap_se_difference": maximum_eap_se_difference,
        "tolerance": 1e-3,
        "grm_source_sha256": sha256_file(grm_path),
        "eap_source_sha256": sha256_file(eap_path),
        "response_generator_source_sha256": sha256_file(generator_path),
        "response_generator_note": "adaptivetesting.generate_response_pattern applies softmax to its GRM category-probability vector; this research adapter does not use it and samples the verified mirt cumulative-logit probabilities directly",
    }


def load_research_inputs(artifact_root: Path) -> ResearchInputs:
    """Validate the isolated split, exact key map, and all five mirt fits."""

    root = artifact_root.resolve()
    response_dir = root / "derived" / "sapa-ipip99-20261013-v1"
    manifest_path = response_dir / "manifest.json"
    calibration_path = response_dir / "calibration.csv"
    evaluation_path = response_dir / "evaluation.csv"
    crosswalk_path = root / "staging" / "sapa-ipip100-item-crosswalk.tsv"
    mirt_root = root / "R-runtime" / "mirt-crosscheck"
    batch_path = mirt_root / "mirt-remaining-domains-20261014-final.json"

    for path in (manifest_path, calibration_path, evaluation_path, crosswalk_path, batch_path):
        if not path.is_file():
            raise ResearchReplayError("research_input_missing", f"required research artifact is missing: {path.name}")

    manifest = _read_json(manifest_path, "response manifest")
    _validate_response_manifest(manifest)
    cal_hash = sha256_file(calibration_path)
    eval_hash = sha256_file(evaluation_path)
    declared_integrity = manifest["output_integrity"]
    if cal_hash != declared_integrity["calibration.csv"]["sha256"]:
        raise ResearchReplayError("calibration_hash_mismatch", "calibration CSV SHA-256 does not match its manifest")
    if eval_hash != declared_integrity["evaluation.csv"]["sha256"]:
        raise ResearchReplayError("evaluation_hash_mismatch", "evaluation CSV SHA-256 does not match its manifest")
    if declared_integrity["calibration.csv"]["record_count"] != 10000:
        raise ResearchReplayError("calibration_count_mismatch", "calibration manifest must declare 10000 records")
    if declared_integrity["evaluation.csv"]["record_count"] != 800:
        raise ResearchReplayError("evaluation_count_mismatch", "evaluation manifest must declare 800 records")

    columns = tuple(manifest.get("response_columns", ()))
    if len(columns) != 99 or len(columns) != len(set(columns)):
        raise ResearchReplayError("response_allowlist_invalid", "response manifest must contain 99 unique item columns")
    _validate_response_csv_header(calibration_path, columns)
    _validate_response_csv_header(evaluation_path, columns)

    crosswalk_rows = _read_crosswalk(crosswalk_path)
    by_domain: dict[str, dict[str, str]] = {domain: {} for domain in EXPECTED_DOMAINS}
    for row in crosswalk_rows:
        domain = row["factor"]
        qid = row["qid"]
        direction = row["key_direction"]
        if domain not in by_domain or not re.fullmatch(r"q_\d+", qid) or direction not in {"positive", "reverse"}:
            raise ResearchReplayError("crosswalk_invalid", "crosswalk contains an unsupported domain, item key, or direction")
        if qid in by_domain[domain]:
            raise ResearchReplayError("crosswalk_duplicate_item", "crosswalk contains a duplicate domain item")
        by_domain[domain][qid] = direction
    if len(crosswalk_rows) != 99 or "q_1483" in {row["qid"] for row in crosswalk_rows}:
        raise ResearchReplayError("crosswalk_item_set_mismatch", "crosswalk must contain the exact 99-item set and omit q_1483")
    if set(columns) != {row["qid"] for row in crosswalk_rows}:
        raise ResearchReplayError("response_crosswalk_mismatch", "response columns do not match the exact-key crosswalk")

    batch = _read_json(batch_path, "mirt batch manifest")
    _validate_batch_manifest(batch, cal_hash)
    domains: list[ResearchDomain] = []
    file_hashes: dict[str, str] = {}
    for domain_name in EXPECTED_DOMAINS:
        subdir, filename = DOMAIN_FILES[domain_name]
        fit_path = mirt_root / subdir / filename
        if not fit_path.is_file():
            raise ResearchReplayError("fit_missing", f"mirt fit is missing: {filename}")
        fit = _read_json(fit_path, f"{domain_name} fit")
        fit_hash = sha256_file(fit_path)
        file_hashes[domain_name] = fit_hash
        domains.append(_validate_fit(fit, domain_name, by_domain[domain_name], cal_hash, fit_hash))

    declared_fit_files = set(batch.get("result_files", ()))
    if declared_fit_files != {filename for _, filename in DOMAIN_FILES.values() if filename != "mirt-extraversion.json"}:
        raise ResearchReplayError("batch_fit_list_mismatch", "mirt batch manifest result file list does not match four-domain bundle")
    _validate_extraversion_provenance(mirt_root / "mirt-extraversion.json", file_hashes["Extraversion"])
    probability_parity = _verify_probability_parity(domains)

    source = manifest["source"]
    return ResearchInputs(
        root=root,
        response_dir=response_dir,
        calibration_sha256=cal_hash,
        evaluation_sha256=eval_hash,
        source_sha256=source["sha256"],
        source_reference=source["reference"],
        source_license=source["license"],
        source_population=source["population"],
        response_columns=columns,
        response_manifest_sha256=sha256_file(manifest_path),
        crosswalk_sha256=sha256_file(crosswalk_path),
        batch_manifest_sha256=sha256_file(batch_path),
        probability_parity=probability_parity,
        domains=tuple(domains),
    )


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchReplayError("invalid_json", f"{label} is not readable valid JSON") from exc
    if not isinstance(value, dict):
        raise ResearchReplayError("invalid_json_root", f"{label} root must be an object")
    return value


def _validate_research_cat_config(config: CATConfig, domains: Sequence[ResearchDomain]) -> None:
    """Reject settings the research adapter cannot faithfully honor."""

    if not domains:
        raise ResearchReplayError("research_config_domains_missing", "research config requires at least one validated domain")
    _validate_research_config_fields(config)
    minimum_domain_size = min(len(domain.items) for domain in domains)
    if config.max_items > minimum_domain_size:
        raise ResearchReplayError(
            "research_config_item_limit_invalid",
            f"max_items must not exceed the smallest selected domain item count ({minimum_domain_size})",
        )


def _validate_research_config_fields(config: CATConfig) -> None:
    unsupported = (
        config.model != "GRM"
        or config.estimator != "EAP"
        or config.selection_method != "MFI"
        or config.initial_theta != 0.0
        or config.prior_mean != 0.0
        or config.prior_sd != 1.0
        or config.optimization_interval != (-4.0, 4.0)
        or config.exposure_control != "none"
        or config.content_balancing != "none"
        or config.seed is None
        or type(config.seed) is not int
        or config.seed < 0
    )
    if unsupported:
        raise ResearchReplayError(
            "research_config_unsupported",
            "research adapter requires GRM/EAP/MFI, N(0,1), initial theta 0, interval [-4,4], no exposure/content balancing, and a fixed non-negative seed",
        )


def load_research_cat_config(
    path: Path,
    *,
    expected_population: str,
    domains: Sequence[ResearchDomain],
) -> ResearchCATConfig:
    envelope = _read_json(path, "research CAT config")
    expected_envelope_keys = {
        "format_version",
        "status",
        "research_only",
        "publication_status",
        "psychological_interpretation_allowed",
        "human_curated",
        "source_population",
        "config",
    }
    if set(envelope) != expected_envelope_keys:
        raise ResearchReplayError("research_config_schema_invalid", "research config envelope fields do not match the research-only schema")
    if (
        envelope.get("format_version") != "cat-research-config.v1"
        or envelope.get("status") != "candidate_research_only"
        or envelope.get("research_only") is not True
        or envelope.get("publication_status") != "not_approved_for_publication_or_operational_use"
        or envelope.get("psychological_interpretation_allowed") is not False
        or envelope.get("human_curated") is not False
        or envelope.get("source_population") != expected_population
    ):
        raise ResearchReplayError("research_config_metadata_invalid", "research config metadata must stay candidate-only and match the source population")
    raw_cat_config = envelope.get("config")
    required_config_keys = {
        "config_version",
        "model",
        "estimator",
        "selection_method",
        "min_items",
        "max_items",
        "se_threshold",
        "initial_theta",
        "prior_mean",
        "prior_sd",
        "optimization_interval",
        "seed",
        "exposure_control",
        "content_balancing",
    }
    if not isinstance(raw_cat_config, dict) or set(raw_cat_config) != required_config_keys:
        raise ResearchReplayError("research_config_schema_invalid", "config must contain exactly the supported CATConfig fields")
    try:
        config = CATConfig.from_dict(raw_cat_config)
    except Exception as exc:
        raise ResearchReplayError("research_config_invalid", "research CAT parameters failed CATConfig validation") from exc
    _validate_research_cat_config(config, domains)
    return ResearchCATConfig(
        envelope=envelope,
        cat=config,
        file_sha256=sha256_file(path),
        content_sha256=_canonical_sha256(envelope),
    )


def _validate_response_manifest(manifest: Mapping[str, object]) -> None:
    source = manifest.get("source")
    sampling = manifest.get("sampling")
    if (
        manifest.get("format_version") != "research-response.v1"
        or manifest.get("research_only") is not True
        or manifest.get("publication_status") != "not_approved_for_publication_or_operational_use"
        or manifest.get("psychological_interpretation_allowed") is not False
        or not isinstance(source, Mapping)
        or not isinstance(sampling, Mapping)
    ):
        raise ResearchReplayError("response_manifest_ineligible", "response manifest is not the approved research-only split")
    if (
        source.get("license") != "CC0-1.0"
        or source.get("sha256") != EXPECTED_SOURCE_SHA256
        or "10.7910/DVN/C40K1U" not in str(source.get("reference", ""))
        or "Self-selected Internet respondents" not in str(source.get("population", ""))
        or sampling.get("source_record_count") != 128464
        or sampling.get("calibration_record_count") != 10000
        or sampling.get("evaluation_record_count") != 800
        or sampling.get("seed") != 20261013
        or sampling.get("splits_disjoint") is not True
        or sampling.get("source_row_identifiers_written") is not False
    ):
        raise ResearchReplayError("response_manifest_scope_mismatch", "response manifest provenance or split controls differ")
    if tuple(manifest.get("ordinal_values", ())) != (1, 2, 3, 4, 5, 6):
        raise ResearchReplayError("category_contract_mismatch", "SAPA source categories must be exactly 1 through 6")
    missing = manifest.get("missing_policy")
    if not isinstance(missing, Mapping) or missing.get("blank_is_missing") is not True or missing.get("missing_preserved_as_empty_cells") is not True:
        raise ResearchReplayError("missing_policy_mismatch", "source missing values must remain empty cells")


def _validate_response_csv_header(path: Path, expected_columns: tuple[str, ...]) -> None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            header = next(reader)
    except (OSError, csv.Error, StopIteration) as exc:
        raise ResearchReplayError("response_header_invalid", "response CSV header cannot be read") from exc
    if tuple(header) != expected_columns:
        raise ResearchReplayError("response_header_mismatch", "response CSV must contain exactly the manifest item columns")


def _read_crosswalk(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t", strict=True)
            expected = ["qid", "item", "ipip100_code", "factor", "key_direction"]
            if reader.fieldnames != expected:
                raise ResearchReplayError("crosswalk_header_invalid", "crosswalk header does not match the exact-key schema")
            rows = list(reader)
    except (OSError, csv.Error) as exc:
        raise ResearchReplayError("crosswalk_invalid", "crosswalk cannot be parsed") from exc
    return rows


def _validate_batch_manifest(batch: Mapping[str, object], calibration_sha256: str) -> None:
    model = batch.get("model")
    expected_model = {
        "package": "mirt",
        "version": "1.47",
        "itemtype": "graded",
        "factors": 1,
        "method": "EM",
        "latent_distribution": "Gaussian N(0,1)",
        "quadrature_points": 41,
        "maximum_cycles": 1000,
    }
    if (
        batch.get("status") != "research_only_batch_completed"
        or batch.get("source_sha256") != calibration_sha256
        or batch.get("source_records") != 10000
        or batch.get("fitted_domains") != [d for d in EXPECTED_DOMAINS if d != "Extraversion"]
        or model != expected_model
    ):
        raise ResearchReplayError("fit_batch_provenance_mismatch", "mirt batch manifest does not match the approved four-domain fit")


def _validate_fit(
    fit: Mapping[str, object],
    domain: str,
    exact_keys: Mapping[str, str],
    calibration_sha256: str,
    fit_sha256: str,
) -> ResearchDomain:
    model = fit.get("model")
    fit_summary = fit.get("fit")
    raw_items = fit.get("item_parameters")
    expected_model = {
        "package": "mirt",
        "version": "1.47",
        "itemtype": "graded",
        "factors": 1,
        "method": "EM",
        "latent_distribution": "Gaussian N(0,1)",
        "quadrature_points": 41,
        "maximum_cycles": 1000,
        "standard_errors": False,
    }
    missing_handling = model.get("missing_handling") if isinstance(model, Mapping) else None
    if (
        fit.get("domain") != domain
        or fit.get("status") not in {"research_only_fit_converged", "research_only_single_domain_crosscheck"}
        or fit.get("source_sha256") != calibration_sha256
        or fit.get("calibration_records") != 10000
        or fit.get("reverse_key_recode") != "7 - observed response; missing values retained"
        or not isinstance(model, Mapping)
        or any(model.get(key) != value for key, value in expected_model.items())
        or not isinstance(missing_handling, str)
        or "NA" not in missing_handling
        or "imputation" not in missing_handling
        or "complete-case" not in missing_handling
        or not isinstance(fit_summary, Mapping)
        or fit_summary.get("converged") is not True
        or type(fit_summary.get("iterations")) is not int
        or fit_summary.get("iterations", 0) < 1
        or not isinstance(raw_items, list)
    ):
        raise ResearchReplayError("fit_provenance_mismatch", f"{domain} fit is not a converged mirt 1.47 one-factor GRM on this calibration split")
    all_missing = fit.get("all_missing_records_retained", fit.get("all_missing_records_retained_in_input"))
    omitted = fit.get("all_missing_rows_omitted_as_informationless")
    estimation_rows = fit.get("estimation_rows_used")
    if (
        type(all_missing) is not int
        or type(omitted) is not int
        or type(estimation_rows) is not int
        or not 0 <= all_missing < 10000
        or omitted != all_missing
        or estimation_rows != 10000 - all_missing
    ):
        raise ResearchReplayError("fit_missing_data_mismatch", f"{domain} fit does not retain and account for planned missingness as declared")

    actual: dict[str, ResearchItem] = {}
    for item in raw_items:
        if not isinstance(item, Mapping):
            raise ResearchReplayError("fit_item_invalid", f"{domain} fit contains a malformed item")
        qid = item.get("qid")
        direction = item.get("key_direction")
        if not isinstance(qid, str) or qid in actual or qid not in exact_keys:
            raise ResearchReplayError("fit_item_set_mismatch", f"{domain} fit has an unknown or duplicate item key")
        if direction != exact_keys[qid] or item.get("reverse_recoding_applied") is not (direction == "reverse"):
            raise ResearchReplayError("fit_direction_mismatch", f"{domain} item key direction does not match the exact crosswalk")
        slope = item.get("a")
        thresholds = item.get("thresholds")
        if (
            isinstance(slope, bool)
            or not isinstance(slope, (int, float))
            or not math.isfinite(float(slope))
            or float(slope) <= 0
            or not isinstance(thresholds, list)
            or len(thresholds) != 5
        ):
            raise ResearchReplayError("fit_parameter_invalid", f"{domain} item parameters are invalid")
        try:
            threshold_values = tuple(float(value) for value in thresholds)
        except (TypeError, ValueError) as exc:
            raise ResearchReplayError("fit_parameter_invalid", f"{domain} thresholds must be numeric") from exc
        if any(not math.isfinite(value) for value in threshold_values) or any(
            left >= right for left, right in zip(threshold_values, threshold_values[1:])
        ):
            raise ResearchReplayError("fit_thresholds_invalid", f"{domain} thresholds must be finite and strictly increasing")
        counts = item.get("observed_category_counts")
        if not isinstance(counts, Mapping) or set(counts) != {str(value) for value in range(1, 7)}:
            raise ResearchReplayError("fit_category_support_invalid", f"{domain} item must report all six source categories")
        if any(type(counts[str(value)]) is not int or counts[str(value)] <= 0 for value in range(1, 7)):
            raise ResearchReplayError("fit_category_support_invalid", f"{domain} item must have positive observed count in all six categories")
        actual[qid] = ResearchItem(qid, direction, float(slope), threshold_values)

    if set(actual) != set(exact_keys) or len(actual) != len(exact_keys):
        raise ResearchReplayError("fit_item_set_mismatch", f"{domain} fit item list differs from its exact-key crosswalk")
    if (
        fit.get("exact_key_item_count") != len(actual)
        or fit.get("reverse_keyed_items") != sum(item.key_direction == "reverse" for item in actual.values())
        or fit.get("positive_keyed_items") != sum(item.key_direction == "positive" for item in actual.values())
    ):
        raise ResearchReplayError("fit_direction_count_mismatch", f"{domain} top-level direction or item counts differ from its item keys")
    if domain == "Conscientiousness" and (len(actual) != 19 or "q_1483" in actual):
        raise ResearchReplayError("conscientiousness_subset_mismatch", "Conscientiousness must use the exact 19-item set excluding q_1483")
    if domain != "Conscientiousness" and len(actual) != 20:
        raise ResearchReplayError("fit_item_count_mismatch", f"{domain} fit must contain exactly 20 items")
    warnings_value = fit_summary.get("warnings", [])
    if isinstance(warnings_value, str):
        warnings = (warnings_value,) if warnings_value else ()
    elif isinstance(warnings_value, list) and all(isinstance(value, str) for value in warnings_value):
        warnings = tuple(warnings_value)
    else:
        raise ResearchReplayError("fit_warnings_invalid", f"{domain} fit warning metadata is malformed")
    return ResearchDomain(
        name=domain,
        items=tuple(actual.values()),
        fit_sha256=fit_sha256,
        fit_model=dict(model),
        fit_iterations=fit_summary["iterations"],
        fit_warnings=warnings,
    )


def _validate_extraversion_provenance(path: Path, expected_sha256: str) -> None:
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise ResearchReplayError("extraversion_fit_hash_mismatch", "Extraversion fit hash changed during input validation")


def _engine_items(items: Sequence[ResearchItem], config: CATConfig) -> _EngineRun:
    _validate_research_config_fields(config)
    engine_items: list[object] = []
    for index, item in enumerate(items):
        engine_item = adt.TestItem()
        engine_item.id = index
        engine_item.a = item.a
        engine_item.b = list(item.thresholds)
        engine_item.additional_properties = {"qid": item.qid}
        engine_items.append(engine_item)
    pool = adt.ItemPool(engine_items)
    engine = adt.TestAssembler(
        item_pool=pool,
        simulation_id="research-aggregate-run",
        participant_id="virtual-case-in-memory-only",
        ability_estimator={"EAP": adt.ExpectedAPosteriori}[config.estimator],
        estimator_args={
            "prior": adt.NormalPrior(config.prior_mean, config.prior_sd),
            "optimization_interval": config.optimization_interval,
            "model": config.model,
        },
        item_selector={"MFI": adt.maximum_information_criterion}[config.selection_method],
        item_selector_args={"model": config.model},
        model_type=config.model,
        initial_ability_level=config.initial_theta,
        simulation=False,
        debug=False,
    )
    # adaptivetesting deep-copies the pool; retain references to its owned items.
    owned_items = {
        str(engine_item.additional_properties["qid"]): engine_item
        for engine_item in engine.item_pool.test_items
    }
    return _EngineRun(
        engine,
        owned_items,
        {item.qid: item for item in items},
        theta=float(config.initial_theta),
        se=float(config.prior_sd),
    )


def _submit(run: _EngineRun, selected_item: object, score: int) -> None:
    if type(score) is not int or score not in range(6):
        raise ResearchReplayError("provider_category_invalid", "provider category must be an integer index from 0 through 5")
    engine = run.engine
    engine.response_pattern.append(score)
    engine.answered_items.append(selected_item)
    try:
        estimate, standard_error = engine.estimate_ability_level()
    except Exception as exc:
        raise ResearchReplayError("eap_estimation_failed", "adaptivetesting EAP estimation failed for the current research path") from exc
    theta = float(estimate)
    se = float(standard_error)
    if not math.isfinite(theta) or not math.isfinite(se) or se <= 0:
        raise ResearchReplayError("eap_estimate_nonfinite", "adaptivetesting returned a non-finite research estimate")
    run.theta = theta
    run.se = se
    run.engine.ability_level = theta
    run.engine.standard_error = se
    run.engine.item_pool.delete_item(selected_item)
    run.answered += 1


def _stopping_reason(run: _EngineRun, config: CATConfig) -> str | None:
    if run.answered < config.min_items:
        return None
    if config.se_threshold is not None and run.se <= config.se_threshold:
        return "se_threshold_reached"
    if run.answered >= config.max_items:
        return "max_items_reached"
    if not run.engine.item_pool.test_items:
        return "item_bank_exhausted"
    return None


def _selected_qid(run: _EngineRun) -> tuple[str, object]:
    try:
        item = run.engine.get_next_item()
        qid = str(item.additional_properties["qid"])
    except Exception as exc:
        raise ResearchReplayError("mfi_selection_failed", "adaptivetesting MFI selection failed") from exc
    if qid not in run.items_by_qid:
        raise ResearchReplayError("provider_item_mapping_invalid", "adaptivetesting returned an item outside the validated research bundle")
    return qid, item


def _sample_grm_category(theta: float, item: ResearchItem, rng: random.Random) -> int:
    draw = rng.random()
    cumulative = 0.0
    for score, probability in enumerate(_grm_category_probabilities(theta, item)):
        cumulative += probability
        if draw < cumulative:
            return score
    return 5


def _new_domain_summary(domain: ResearchDomain) -> dict:
    return {
        "domain": domain.name,
        "item_count": len(domain.items),
        "item_key_direction_counts": {
            "positive": sum(item.key_direction == "positive" for item in domain.items),
            "reverse": sum(item.key_direction == "reverse" for item in domain.items),
        },
        "fit_sha256": domain.fit_sha256,
        "fit_model": dict(domain.fit_model),
        "fit_converged": True,
        "fit_iterations": domain.fit_iterations,
        "fit_warnings": list(domain.fit_warnings),
    }


def observed_answer_replay(
    domain: ResearchDomain,
    response_rows: Iterable[Mapping[str, str]],
    config: CATConfig,
    *,
    expected_records: int = 800,
) -> dict:
    """Replay actual observed responses; censor immediately on selected NA."""

    _validate_research_cat_config(config, [domain])
    exposures = dict.fromkeys((item.qid for item in domain.items), 0)
    answered_exposures = dict.fromkeys((item.qid for item in domain.items), 0)
    stops: dict[str, int] = {}
    administered_counts: dict[str, int] = {}
    total = completed = censored_before_min = censored_after_min = no_domain_response = 0
    for row in response_rows:
        total += 1
        if total > expected_records:
            raise ResearchReplayError("evaluation_count_mismatch", "evaluation CSV contains more than the declared record count")
        if all(row.get(item.qid, "").strip() == "" for item in domain.items):
            no_domain_response += 1
            stops["no_domain_response"] = stops.get("no_domain_response", 0) + 1
            continue
        run = _engine_items(domain.items, config)
        stop_reason: str | None = None
        for _ in range(config.max_items):
            qid, selected_item = _selected_qid(run)
            exposures[qid] += 1
            raw_text = row.get(qid)
            if raw_text is None:
                raise ResearchReplayError("evaluation_column_missing", "evaluation row does not contain the selected exact-key item")
            raw_text = raw_text.strip()
            if raw_text == "":
                stop_reason = "source_response_unavailable"
                if run.answered < config.min_items:
                    censored_before_min += 1
                else:
                    censored_after_min += 1
                break
            if not raw_text.isdecimal():
                raise ResearchReplayError("invalid_source_category", f"evaluation column {qid} is not an ordinal source category")
            if raw_text not in {str(value) for value in range(1, 7)}:
                raise ResearchReplayError("invalid_source_category", f"evaluation column {qid} is not a canonical 1..6 category")
            score = score_source_response(int(raw_text), run.research_items_by_qid[qid].key_direction)
            _submit(run, selected_item, score)
            answered_exposures[qid] += 1
            stop_reason = _stopping_reason(run, config)
            if stop_reason:
                completed += 1
                break
        if stop_reason is None:
            # Defensive path for a misconfigured maximum or provider loop.
            stop_reason = "maximum_loop_exhausted_without_stop"
        stops[stop_reason] = stops.get(stop_reason, 0) + 1
        administered_counts[str(run.answered)] = administered_counts.get(str(run.answered), 0) + 1
    if total != expected_records:
        raise ResearchReplayError("evaluation_count_mismatch", f"evaluation CSV has {total} rows; expected {expected_records}")
    if total != completed + censored_before_min + censored_after_min + no_domain_response:
        raise ResearchReplayError("replay_accounting_mismatch", "observed replay counts do not reconcile to the fixed denominator")
    return {
        "mode": "observed_answer_replay",
        "records_started": total,
        "completed_paths": completed,
        "censored_before_minimum": censored_before_min,
        "censored_after_minimum": censored_after_min,
        "selected_source_unanswered_count": censored_before_min + censored_after_min,
        "no_domain_response": no_domain_response,
        "effective_completed_n": completed,
        "stop_reason_counts": dict(sorted(stops.items())),
        "observed_items_answered_count_distribution": dict(sorted(administered_counts.items(), key=lambda pair: int(pair[0]))),
        "item_selection_exposure_counts": dict(sorted(exposures.items())),
        "item_observed_answer_counts": dict(sorted(answered_exposures.items())),
        "missing_policy": "selected_source_NA_censors_immediately_without_scoring_or_reselection",
    }


def _domain_seed(seed: int, domain: str) -> int:
    digest = hashlib.sha256(f"{seed}:{domain}:model-forward".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def model_generated_forward_simulation(
    domain: ResearchDomain,
    config: CATConfig,
    *,
    n_cases: int = 800,
) -> dict:
    """Run virtual adaptive paths from the fitted GRM; retain aggregates only."""

    _validate_research_cat_config(config, [domain])
    if type(n_cases) is not int or n_cases < 1 or n_cases > 800:
        raise ResearchReplayError("forward_case_count_invalid", "model-generated forward run supports 1 through 800 cases per domain")
    if type(config.seed) is not int or config.seed < 0:
        raise ResearchReplayError("seed_invalid", "research seed must be a non-negative integer")
    rng = random.Random(_domain_seed(config.seed, domain.name))
    stop_counts: dict[str, int] = {}
    exposures = dict.fromkeys((item.qid for item in domain.items), 0)
    length_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    error_sum = squared_error_sum = absolute_error_sum = se_sum = 0.0
    completed = total_answers = 0
    for _ in range(n_cases):
        true_theta = rng.gauss(0.0, 1.0)
        run = _engine_items(domain.items, config)
        reason: str | None = None
        path_completed = False
        for _ in range(config.max_items):
            try:
                qid, selected_item = _selected_qid(run)
                exposures[qid] += 1
                generated_score = _sample_grm_category(true_theta, run.research_items_by_qid[qid], rng)
                _submit(run, selected_item, generated_score)
            except ResearchReplayError as exc:
                reason = exc.code
                error_counts[reason] = error_counts.get(reason, 0) + 1
                break
            reason = _stopping_reason(run, config)
            if reason:
                completed += 1
                path_completed = True
                break
        if reason is None:
            reason = "maximum_loop_exhausted_without_stop"
            error_counts[reason] = error_counts.get(reason, 0) + 1
        stop_counts[reason] = stop_counts.get(reason, 0) + 1
        length_counts[str(run.answered)] = length_counts.get(str(run.answered), 0) + 1
        total_answers += run.answered
        if path_completed and run.answered and math.isfinite(run.se) and math.isfinite(run.theta):
            difference = run.theta - true_theta
            error_sum += difference
            squared_error_sum += difference * difference
            absolute_error_sum += abs(difference)
            se_sum += run.se
    metric_n = completed
    metrics = None
    if metric_n:
        metrics = {
            "bias": error_sum / metric_n,
            "rmse": math.sqrt(squared_error_sum / metric_n),
            "mae": absolute_error_sum / metric_n,
            "mean_se": se_sum / metric_n,
        }
    return {
        "mode": "model_generated_forward",
        "case_count": n_cases,
        "completed_paths": completed,
        "forward_seed": _domain_seed(config.seed, domain.name),
        "theta_distribution": "Gaussian N(0,1)",
        "response_generator": "research direct mirt GRM categorical draw v1",
        "aggregate_metrics": metrics,
        "completed_metric_n": metric_n,
        "mean_items_answered": total_answers / n_cases,
        "item_count_distribution": dict(sorted(length_counts.items(), key=lambda pair: int(pair[0]))),
        "stop_reason_counts": dict(sorted(stop_counts.items())),
        "error_counts": dict(sorted(error_counts.items())),
        "item_selection_exposure_counts": dict(sorted(exposures.items())),
        "individual_theta_or_response_rows_written": False,
    }


def _evaluation_rows(path: Path, expected_columns: tuple[str, ...]) -> Iterable[Mapping[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if tuple(reader.fieldnames or ()) != expected_columns:
                raise ResearchReplayError("evaluation_header_mismatch", "evaluation CSV header changed after provenance validation")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ResearchReplayError("evaluation_row_malformed", "evaluation CSV contains a malformed response row")
                yield row
    except (OSError, csv.Error) as exc:
        raise ResearchReplayError("evaluation_csv_invalid", "evaluation CSV cannot be read") from exc


def _domain_checkpoint_stem(domain_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", domain_name.casefold()).strip("-")


def _run_identity(
    inputs: ResearchInputs,
    research_config: ResearchCATConfig,
    *,
    mode: str,
    domains: Sequence[ResearchDomain],
    forward_cases: int | None,
) -> dict:
    code_path = Path(__file__).resolve()
    return {
        "format_version": RUN_FORMAT_VERSION,
        "code_sha256": sha256_file(code_path),
        "runtime": {
            "adaptivetesting_version": importlib.metadata.version("adaptivetesting"),
            "python_version": platform.python_version(),
        },
        "input_sha256": {
            "source_dataset": inputs.source_sha256,
            "calibration": inputs.calibration_sha256,
            "evaluation": inputs.evaluation_sha256,
            "response_manifest": inputs.response_manifest_sha256,
            "crosswalk": inputs.crosswalk_sha256,
            "mirt_batch_manifest": inputs.batch_manifest_sha256,
            "fits": {domain.name: domain.fit_sha256 for domain in inputs.domains},
            "probability_parity": _canonical_sha256(inputs.probability_parity),
        },
        "config": {
            "file_sha256": research_config.file_sha256,
            "content_sha256": research_config.content_sha256,
            "parsed": research_config.cat.to_dict(),
        },
        "mode": mode,
        "domains": [domain.name for domain in domains],
        "observed_records_per_domain": 800 if mode in {"both", "observed-replay"} else None,
        "forward_cases_per_domain": forward_cases if mode in {"both", "model-forward"} else None,
    }


def _build_domain_result(
    inputs: ResearchInputs,
    domain: ResearchDomain,
    config: CATConfig,
    *,
    mode: str,
    forward_cases: int | None,
) -> dict:
    result = _new_domain_summary(domain)
    if mode in {"both", "observed-replay"}:
        result["observed_replay"] = observed_answer_replay(
            domain,
            _evaluation_rows(inputs.response_dir / "evaluation.csv", inputs.response_columns),
            config,
            expected_records=800,
        )
    if mode in {"both", "model-forward"}:
        if forward_cases is None:
            raise ResearchReplayError("forward_case_count_required", "forward_cases is required for model-forward mode")
        result["model_forward_simulation"] = model_generated_forward_simulation(
            domain,
            config,
            n_cases=forward_cases,
        )
    return result


def _run_summary(
    inputs: ResearchInputs,
    research_config: ResearchCATConfig,
    run_id: str,
    identity: Mapping[str, object],
    domain_results: Mapping[str, object],
) -> dict:
    config = research_config.cat
    has_forward_errors = any(
        result["model_forward_simulation"]["completed_paths"]
        != result["model_forward_simulation"]["case_count"]
        or bool(result["model_forward_simulation"]["error_counts"])
        for result in domain_results.values()
        if "model_forward_simulation" in result
    )
    return {
        "format_version": FORMAT_VERSION,
        "run_id": run_id,
        "run_status": "research_only_completed_with_errors" if has_forward_errors else "research_only_completed",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "psychological_interpretation_allowed": False,
        "run_identity_sha256": _canonical_sha256(identity),
        "mode": identity["mode"],
        "source": {
            "reference": inputs.source_reference,
            "license": inputs.source_license,
            "population": inputs.source_population,
            "source_sha256": inputs.source_sha256,
            "calibration_sha256": inputs.calibration_sha256,
            "calibration_records": 10000,
            "evaluation_sha256": inputs.evaluation_sha256,
            "evaluation_records": 800,
            "evaluation_seed": 20261013,
            "splits_disjoint": True,
        },
        "input_artifact_sha256": dict(identity["input_sha256"]),
        "probability_parity": dict(inputs.probability_parity),
        "research_config": {
            "status": research_config.envelope["status"],
            "file_sha256": research_config.file_sha256,
            "content_sha256": research_config.content_sha256,
            "metadata": {key: value for key, value in research_config.envelope.items() if key != "config"},
            "parameters": config.to_dict(),
        },
        "engine": {
            "package": "adaptivetesting",
            "version": importlib.metadata.version("adaptivetesting"),
            "python": platform.python_version(),
            "measurement_model": config.model,
            "estimator": config.estimator,
            "selection_method": config.selection_method,
            "min_items": config.min_items,
            "max_items": config.max_items,
            "se_threshold": config.se_threshold,
            "prior": {"family": "Gaussian", "mean": config.prior_mean, "sd": config.prior_sd},
            "initial_theta": config.initial_theta,
            "optimization_interval": list(config.optimization_interval),
            "exposure_control": config.exposure_control,
            "content_balancing": config.content_balancing,
            "forward_seed": config.seed,
            "simulation_theta_distribution": "Gaussian N(0,1)",
            "response_generator": "research direct mirt GRM categorical draw v1",
        },
        "domains": dict(domain_results),
        "not_estimated_or_claimed": [
            "person abilities or response rows",
            "clinical meaning",
            "student or school norms",
            "psychometric validity",
            "published scale or CAT bank readiness",
            "five-dimensional MIRT",
        ],
    }


def _external_output_root(output_root: Path) -> Path:
    root = output_root.resolve()
    project_root = Path(__file__).resolve().parents[4]
    try:
        root.relative_to(project_root)
    except ValueError:
        pass
    else:
        raise ResearchReplayError("output_inside_repository", "research output directory must be outside the repository")
    if not root.is_dir():
        raise ResearchReplayError("output_root_missing", "output root must already exist")
    return root


def _write_json_atomic(path: Path, value: Mapping[str, object]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.tmp-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise ResearchReplayError("checkpoint_write_failed", "could not atomically write an aggregate research checkpoint") from exc


def _read_run_manifest(path: Path, identity: Mapping[str, object]) -> dict:
    manifest = _read_json(path, "research run manifest")
    identity_sha = _canonical_sha256(identity)
    if (
        manifest.get("format_version") != RUN_FORMAT_VERSION
        or manifest.get("identity") != identity
        or manifest.get("identity_sha256") != identity_sha
    ):
        raise ResearchReplayError("resume_identity_mismatch", "saved run identity differs in source, fit, config, code, mode, domain, or run size")
    return manifest


def _validate_checkpoint_result(
    domain_name: str,
    result: Mapping[str, object],
    *,
    mode: str,
    forward_cases: int | None,
) -> None:
    if result.get("domain") != domain_name:
        raise ResearchReplayError("checkpoint_domain_mismatch", "checkpoint result does not match its domain file")
    observed = result.get("observed_replay")
    if mode in {"both", "observed-replay"}:
        if not isinstance(observed, Mapping):
            raise ResearchReplayError("checkpoint_result_incomplete", "checkpoint is missing observed replay aggregate")
        count_keys = (
            "records_started",
            "completed_paths",
            "censored_before_minimum",
            "censored_after_minimum",
            "no_domain_response",
        )
        if any(type(observed.get(key)) is not int or observed[key] < 0 for key in count_keys):
            raise ResearchReplayError("checkpoint_replay_accounting_invalid", "checkpoint replay counts must be non-negative integers")
        if (
            observed.get("records_started") != 800
            or observed.get("records_started")
            != observed.get("completed_paths", 0)
            + observed.get("censored_before_minimum", 0)
            + observed.get("censored_after_minimum", 0)
            + observed.get("no_domain_response", 0)
        ):
            raise ResearchReplayError("checkpoint_replay_accounting_invalid", "checkpoint replay counts do not reconcile")
    forward = result.get("model_forward_simulation")
    if mode in {"both", "model-forward"}:
        if not isinstance(forward, Mapping) or forward.get("case_count") != forward_cases:
            raise ResearchReplayError("checkpoint_result_incomplete", "checkpoint forward case count does not match the run")
        if any(
            type(forward.get(key)) is not int or forward[key] < 0
            for key in ("completed_paths", "completed_metric_n")
        ) or not isinstance(forward.get("stop_reason_counts"), Mapping):
            raise ResearchReplayError("checkpoint_forward_aggregate_invalid", "checkpoint forward metrics must contain valid aggregate counts")
        stop_counts = forward["stop_reason_counts"]
        length_counts = forward.get("item_count_distribution")
        if (
            forward["completed_paths"] > forward_cases
            or forward["completed_metric_n"] > forward["completed_paths"]
            or any(type(value) is not int or value < 0 for value in stop_counts.values())
            or sum(stop_counts.values()) != forward_cases
            or not isinstance(length_counts, Mapping)
            or any(not isinstance(key, str) or not key.isdecimal() or type(value) is not int or value < 0 for key, value in length_counts.items())
            or sum(length_counts.values()) != forward_cases
        ):
            raise ResearchReplayError("checkpoint_forward_accounting_invalid", "checkpoint forward aggregate counts do not reconcile")
        if forward.get("individual_theta_or_response_rows_written") is not False:
            raise ResearchReplayError("checkpoint_privacy_invalid", "checkpoint does not assert aggregate-only output")


def _load_domain_checkpoint(
    path: Path,
    *,
    identity_sha256: str,
    domain_name: str,
    mode: str,
    forward_cases: int | None,
) -> dict:
    checkpoint = _read_json(path, "domain checkpoint")
    result = checkpoint.get("result")
    if (
        checkpoint.get("format_version") != CHECKPOINT_FORMAT_VERSION
        or checkpoint.get("run_identity_sha256") != identity_sha256
        or checkpoint.get("domain") != domain_name
        or checkpoint.get("status") != "completed"
        or not isinstance(result, dict)
        or checkpoint.get("result_sha256") != _canonical_sha256(result)
    ):
        raise ResearchReplayError("checkpoint_integrity_mismatch", "saved domain checkpoint failed identity or aggregate hash validation")
    _validate_checkpoint_result(domain_name, result, mode=mode, forward_cases=forward_cases)
    return result


def run_checkpointed_research(
    inputs: ResearchInputs,
    research_config: ResearchCATConfig,
    *,
    output_root: Path,
    run_id: str,
    mode: str = "both",
    domain_names: Sequence[str] | None = None,
    forward_cases: int | None = None,
    resume: bool = False,
) -> Path:
    """Run or resume one domain at a time, persisting aggregate checkpoints only."""

    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ResearchReplayError("run_id_invalid", "run id contains unsupported characters")
    if mode not in {"both", "observed-replay", "model-forward"}:
        raise ResearchReplayError("run_mode_invalid", "run mode must be both, observed-replay, or model-forward")
    forward_mode = mode in {"both", "model-forward"}
    if forward_mode:
        if type(forward_cases) is not int or not 1 <= forward_cases <= 800:
            raise ResearchReplayError("forward_case_count_invalid", "forward mode requires 1 through 800 cases per domain")
    elif forward_cases is not None:
        raise ResearchReplayError("forward_case_count_unexpected", "forward_cases must be omitted for observed-replay-only mode")

    available = {domain.name: domain for domain in inputs.domains}
    if domain_names is None:
        selected_names = tuple(domain.name for domain in inputs.domains)
    else:
        selected_names = tuple(domain_names)
    if not selected_names or len(selected_names) != len(set(selected_names)) or any(name not in available for name in selected_names):
        raise ResearchReplayError("domain_selection_invalid", "selected domains must be a non-empty unique subset of the validated fits")
    selected_domains = tuple(available[name] for name in selected_names)
    _validate_research_cat_config(research_config.cat, selected_domains)

    identity = _run_identity(
        inputs,
        research_config,
        mode=mode,
        domains=selected_domains,
        forward_cases=forward_cases,
    )
    identity_sha = _canonical_sha256(identity)
    root = _external_output_root(output_root)
    run_dir = root / run_id
    checkpoint_dir = run_dir / "checkpoints"
    run_manifest_path = run_dir / "run_manifest.json"
    summary_path = run_dir / "summary.json"
    if run_dir.exists():
        if not resume:
            raise ResearchReplayError("run_directory_exists", "run directory already exists; use a new run id or explicit resume")
        if not run_manifest_path.is_file() or not checkpoint_dir.is_dir():
            raise ResearchReplayError("resume_state_missing", "existing run lacks the checkpoint protocol manifest")
        run_manifest = _read_run_manifest(run_manifest_path, identity)
        if run_manifest.get("run_status") not in {"in_progress", "research_only_completed", "research_only_completed_with_errors"}:
            raise ResearchReplayError("resume_status_invalid", "saved run status is not resumable")
        if not isinstance(run_manifest.get("completed_domains"), list):
            raise ResearchReplayError("resume_manifest_invalid", "saved completed-domain aggregate list is invalid")
        claimed_completed = run_manifest["completed_domains"]
        if (
            any(type(name) is not str or name not in selected_names for name in claimed_completed)
            or len(claimed_completed) != len(set(claimed_completed))
            or any(not (checkpoint_dir / f"{_domain_checkpoint_stem(name)}.json").is_file() for name in claimed_completed)
        ):
            raise ResearchReplayError("resume_manifest_invalid", "saved manifest claims a domain without a matching checkpoint")
    else:
        if resume:
            raise ResearchReplayError("resume_run_missing", "cannot resume a run directory that does not exist")
        run_dir.mkdir()
        checkpoint_dir.mkdir()
        run_manifest = {
            "format_version": RUN_FORMAT_VERSION,
            "identity": identity,
            "identity_sha256": identity_sha,
            "run_status": "in_progress",
            "completed_domains": [],
        }
        _write_json_atomic(run_manifest_path, run_manifest)

    domain_results: dict[str, dict] = {}
    completed_domains: list[str] = []
    for domain in selected_domains:
        checkpoint_path = checkpoint_dir / f"{_domain_checkpoint_stem(domain.name)}.json"
        if checkpoint_path.exists():
            result = _load_domain_checkpoint(
                checkpoint_path,
                identity_sha256=identity_sha,
                domain_name=domain.name,
                mode=mode,
                forward_cases=forward_cases,
            )
        else:
            result = _build_domain_result(
                inputs,
                domain,
                research_config.cat,
                mode=mode,
                forward_cases=forward_cases,
            )
            _validate_checkpoint_result(domain.name, result, mode=mode, forward_cases=forward_cases)
            checkpoint_record = {
                "format_version": CHECKPOINT_FORMAT_VERSION,
                "run_identity_sha256": identity_sha,
                "domain": domain.name,
                "status": "completed",
                "result_sha256": _canonical_sha256(result),
                "result": result,
            }
            _write_json_atomic(checkpoint_path, checkpoint_record)
        domain_results[domain.name] = result
        completed_domains.append(domain.name)
        run_manifest = {
            "format_version": RUN_FORMAT_VERSION,
            "identity": identity,
            "identity_sha256": identity_sha,
            "run_status": "in_progress",
            "completed_domains": list(completed_domains),
        }
        _write_json_atomic(run_manifest_path, run_manifest)

    summary = _run_summary(inputs, research_config, run_id, identity, domain_results)
    summary_content = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    summary_hash = hashlib.sha256(summary_content.encode("utf-8")).hexdigest()
    if summary_path.exists():
        if sha256_file(summary_path) != summary_hash:
            raise ResearchReplayError("resume_summary_mismatch", "existing final summary differs from validated domain checkpoints")
    else:
        _write_json_atomic(summary_path, summary)
    run_manifest = {
        "format_version": RUN_FORMAT_VERSION,
        "identity": identity,
        "identity_sha256": identity_sha,
        "run_status": summary["run_status"],
        "completed_domains": list(completed_domains),
        "summary_sha256": summary_hash,
    }
    _write_json_atomic(run_manifest_path, run_manifest)
    return summary_path


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate-only SAPA/IPIP99 CAT research replay and model-forward simulation.")
    parser.add_argument("--artifact-root", required=True, type=Path, help="Existing psynova-public-research artifact root")
    parser.add_argument("--config", required=True, type=Path, help="Explicit candidate research-only CAT config JSON")
    parser.add_argument("--output-root", required=True, type=Path, help="Existing external D-drive research run directory")
    parser.add_argument("--run-id", required=True, help="New unique run id; output directory must not exist")
    parser.add_argument("--mode", choices=("both", "observed-replay", "model-forward"), default="both")
    parser.add_argument("--domain", dest="domains", action="append", choices=EXPECTED_DOMAINS, help="Validated fit domain; repeat to select multiple")
    parser.add_argument("--forward-cases", type=int, help="Cases per domain (1..800); required for both/forward modes and omitted in observed-only mode")
    parser.add_argument("--resume", action="store_true", help="Resume only a run whose exact source, fit, config, code and size identity matches")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        inputs = load_research_inputs(args.artifact_root)
        selected_names = tuple(args.domains) if args.domains else tuple(domain.name for domain in inputs.domains)
        available_domains = {domain.name: domain for domain in inputs.domains}
        selected_domains = tuple(available_domains[name] for name in selected_names)
        research_config = load_research_cat_config(
            args.config,
            expected_population=inputs.source_population,
            domains=selected_domains,
        )
        output_path = run_checkpointed_research(
            inputs,
            research_config,
            output_root=args.output_root,
            run_id=args.run_id,
            mode=args.mode,
            domain_names=args.domains,
            forward_cases=args.forward_cases,
            resume=args.resume,
        )
        summary = _read_json(output_path, "completed research summary")
    except ResearchReplayError as exc:
        print(f"research-cat-replay failed [{exc.code}]: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("research-cat-replay failed [io_error]: a required research file could not be read or written", file=sys.stderr)
        return 2
    except Exception:
        print("research-cat-replay failed [unexpected_runtime_error]: CAT research run did not complete", file=sys.stderr)
        return 2
    print(json.dumps({"run_id": args.run_id, "summary_path": str(output_path), "status": summary["run_status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
