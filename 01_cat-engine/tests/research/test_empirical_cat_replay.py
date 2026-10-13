"""Targeted invariants for the aggregate-only SAPA CAT research adapter."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from cat_engine.domain.config import CATConfig
from cat_engine.research import empirical_cat_replay as replay
from cat_engine.research.empirical_cat_replay import (
    ResearchCATConfig,
    ResearchDomain,
    ResearchItem,
    ResearchInputs,
    ResearchReplayError,
    _engine_items,
    _selected_qid,
    _validate_fit,
    _verify_probability_parity,
    load_research_cat_config,
    model_generated_forward_simulation,
    observed_answer_replay,
    run_checkpointed_research,
    score_source_response,
)


def make_domain(count: int = 3, *, name: str = "Test Domain") -> ResearchDomain:
    items = tuple(
        ResearchItem(
            qid=f"q_{index + 1}",
            key_direction="reverse" if index % 2 else "positive",
            a=1.0 + index / 10,
            thresholds=(-1.5, -0.75, 0.0, 0.75, 1.5),
        )
        for index in range(count)
    )
    return ResearchDomain(
        name=name,
        items=items,
        fit_sha256="a" * 64,
        fit_model={"package": "mirt", "version": "1.47", "itemtype": "graded"},
        fit_iterations=12,
        fit_warnings=(),
    )


def make_config(*, minimum: int = 3, maximum: int = 3) -> CATConfig:
    return CATConfig.from_dict(
        {
            "config_version": "research-test-v1",
            "model": "GRM",
            "estimator": "EAP",
            "selection_method": "MFI",
            "min_items": minimum,
            "max_items": maximum,
            "se_threshold": 0.01,
            "initial_theta": 0.0,
            "prior_mean": 0.0,
            "prior_sd": 1.0,
            "optimization_interval": [-4.0, 4.0],
            "seed": 20261014,
            "exposure_control": "none",
            "content_balancing": "none",
        }
    )


def make_research_config(config: CATConfig | None = None) -> ResearchCATConfig:
    cat = config or make_config(minimum=3, maximum=8)
    envelope = {
        "format_version": "cat-research-config.v1",
        "status": "candidate_research_only",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "psychological_interpretation_allowed": False,
        "human_curated": False,
        "source_population": "Self-selected Internet respondents; not a validated school cohort; demographics excluded",
        "config": cat.to_dict(),
    }
    return ResearchCATConfig(envelope, cat, "d" * 64, replay._canonical_sha256(envelope))


def make_inputs(domain: ResearchDomain) -> ResearchInputs:
    return ResearchInputs(
        root=Path("D:/isolated-research"),
        response_dir=Path("D:/isolated-research/derived"),
        calibration_sha256="a" * 64,
        evaluation_sha256="b" * 64,
        source_sha256="c" * 64,
        source_reference="public research source",
        source_license="CC0-1.0",
        source_population="Self-selected Internet respondents; not a validated school cohort; demographics excluded",
        response_columns=tuple(item.qid for item in domain.items),
        response_manifest_sha256="1" * 64,
        crosswalk_sha256="2" * 64,
        batch_manifest_sha256="3" * 64,
        probability_parity={"status": "test fixture"},
        domains=(domain,),
    )


@pytest.mark.parametrize(
    ("raw", "direction", "expected"),
    [
        (1, "positive", 0),
        (6, "positive", 5),
        (1, "reverse", 5),
        (6, "reverse", 0),
        (3, "reverse", 3),
    ],
)
def test_source_category_and_reverse_key_map_to_provider_zero_through_five(raw, direction, expected):
    assert score_source_response(raw, direction) == expected


def test_source_missing_selected_by_mfi_censors_without_reselection_or_scoring():
    domain = make_domain()
    config = make_config()
    first_selected_qid, _ = _selected_qid(_engine_items(domain.items, config))
    rows = [
        {item.qid: ("" if item.qid == first_selected_qid else "4") for item in domain.items}
    ]

    result = observed_answer_replay(domain, rows, config, expected_records=1)

    assert result["records_started"] == 1
    assert result["completed_paths"] == 0
    assert result["censored_before_minimum"] == 1
    assert sum(result["item_selection_exposure_counts"].values()) == 1
    assert sum(result["item_observed_answer_counts"].values()) == 0
    assert result["stop_reason_counts"] == {"source_response_unavailable": 1}
    assert result["missing_policy"] == "selected_source_NA_censors_immediately_without_scoring_or_reselection"


def test_model_generated_forward_is_seed_deterministic_and_aggregate_only():
    domain = make_domain()
    config = make_config()

    first = model_generated_forward_simulation(domain, config, n_cases=24)
    second = model_generated_forward_simulation(domain, config, n_cases=24)

    assert first == second
    assert first["case_count"] == 24
    assert first["theta_distribution"] == "Gaussian N(0,1)"
    assert first["stop_reason_counts"] == {"max_items_reached": 24}
    assert first["completed_metric_n"] == 24
    assert first["individual_theta_or_response_rows_written"] is False
    assert "true_theta" not in first
    assert "response_pattern" not in first
    assert "answers" not in first


def test_public_eap_and_pinned_grm_source_pass_probability_link_gate():
    evidence = _verify_probability_parity([make_domain(count=20)])

    assert evidence["status"] == "source_and_public_eap_likelihood_parity_passed"
    assert evidence["slope_scale"] == 1.0
    assert evidence["source_category_count"] == 6
    assert evidence["provider_score_indexes"] == [0, 1, 2, 3, 4, 5]
    assert evidence["all_item_probability_vectors_checked"] == 20 * 17
    assert evidence["public_eap_likelihood_cases"] == 6
    assert evidence["maximum_eap_mean_difference"] <= evidence["tolerance"]
    assert evidence["maximum_eap_se_difference"] <= evidence["tolerance"]
    assert "does not use it" in evidence["response_generator_note"]


def test_fit_direction_mismatch_fails_closed():
    domain = make_domain(count=20)
    expected_keys = {item.qid: item.key_direction for item in domain.items}
    fit_items = []
    for item in domain.items:
        direction = item.key_direction
        if item.qid == "q_1":
            direction = "reverse"
        fit_items.append(
            {
                "qid": item.qid,
                "key_direction": direction,
                "reverse_recoding_applied": direction == "reverse",
                "a": item.a,
                "thresholds": list(item.thresholds),
                "observed_category_counts": {str(value): 10 for value in range(1, 7)},
            }
        )
    fit = {
        "status": "research_only_fit_converged",
        "domain": domain.name,
        "source_sha256": "b" * 64,
        "calibration_records": 10000,
        "reverse_key_recode": "7 - observed response; missing values retained",
        "model": {
            "package": "mirt",
            "version": "1.47",
            "itemtype": "graded",
            "factors": 1,
            "method": "EM",
            "latent_distribution": "Gaussian N(0,1)",
            "quadrature_points": 41,
            "maximum_cycles": 1000,
            "standard_errors": False,
            "missing_handling": "NA retained; no imputation or complete-case deletion",
        },
        "fit": {"converged": True, "iterations": 12, "warnings": []},
        "estimation_rows_used": 10000,
        "all_missing_records_retained_in_input": 0,
        "all_missing_rows_omitted_as_informationless": 0,
        "exact_key_item_count": 20,
        "reverse_keyed_items": sum(item.key_direction == "reverse" for item in domain.items),
        "positive_keyed_items": sum(item.key_direction == "positive" for item in domain.items),
        "item_parameters": fit_items,
    }

    with pytest.raises(ResearchReplayError) as error:
        _validate_fit(fit, domain.name, expected_keys, "b" * 64, "c" * 64)

    assert error.value.code == "fit_direction_mismatch"


def test_wrong_evaluation_denominator_fails_closed():
    with pytest.raises(ResearchReplayError) as error:
        observed_answer_replay(make_domain(), [], make_config(), expected_records=800)
    assert error.value.code == "evaluation_count_mismatch"


def test_research_config_loader_requires_candidate_metadata_and_tracks_both_hashes(tmp_path):
    import json

    path = tmp_path / "candidate.json"
    envelope = make_research_config().envelope
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    loaded = load_research_cat_config(
        path,
        expected_population=envelope["source_population"],
        domains=(make_domain(count=20),),
    )

    assert loaded.file_sha256 == replay.sha256_file(path)
    assert loaded.content_sha256 == replay._canonical_sha256(envelope)
    assert loaded.cat.max_items == 8


@pytest.mark.parametrize(
    "updates",
    [
        {"model": "2PL"},
        {"estimator": "MLE"},
        {"selection_method": "random"},
        {"prior_sd": 2.0},
        {"initial_theta": 0.1},
        {"optimization_interval": [-3.0, 3.0]},
        {"exposure_control": "randomesque"},
        {"content_balancing": "by_domain"},
    ],
)
def test_research_config_rejects_algorithm_fields_the_adapter_cannot_honor(updates):
    values = make_config(minimum=3, maximum=8).to_dict()
    values.update(updates)
    if isinstance(values["optimization_interval"], list):
        values["optimization_interval"] = tuple(values["optimization_interval"])
    config = CATConfig(**values)

    with pytest.raises(ResearchReplayError) as error:
        replay._validate_research_cat_config(config, (make_domain(count=20),))

    assert error.value.code == "research_config_unsupported"


def test_research_config_rejects_item_cap_larger_than_any_domain_without_clamping():
    config = make_config(minimum=3, maximum=20)
    with pytest.raises(ResearchReplayError) as error:
        replay._validate_research_cat_config(config, (make_domain(count=19),))
    assert error.value.code == "research_config_item_limit_invalid"


def test_research_config_item_cap_is_checked_against_selected_domain_size(tmp_path):
    import json

    envelope = make_research_config(make_config(minimum=3, maximum=20)).envelope
    path = tmp_path / "selected-domain-candidate.json"
    path.write_text(json.dumps(envelope), encoding="utf-8")

    loaded = load_research_cat_config(
        path,
        expected_population=envelope["source_population"],
        domains=(make_domain(count=20),),
    )

    assert loaded.cat.max_items == 20


def test_checkpoint_resume_reuses_only_hash_bound_aggregate_and_rejects_tampering(tmp_path, monkeypatch):
    import json

    domain = make_domain(count=20)
    inputs = make_inputs(domain)
    config = make_research_config()
    output_root = tmp_path / "runs"
    output_root.mkdir()
    summary_path = run_checkpointed_research(
        inputs,
        config,
        output_root=output_root,
        run_id="resume-test-run",
        mode="model-forward",
        domain_names=(domain.name,),
        forward_cases=2,
    )
    checkpoint = output_root / "resume-test-run" / "checkpoints" / "test-domain.json"
    assert summary_path.is_file() and checkpoint.is_file()

    def must_reuse(*_args, **_kwargs):
        raise AssertionError("valid checkpoint should be reused without recomputing the domain")

    monkeypatch.setattr(replay, "_build_domain_result", must_reuse)
    resumed = run_checkpointed_research(
        inputs,
        config,
        output_root=output_root,
        run_id="resume-test-run",
        mode="model-forward",
        domain_names=(domain.name,),
        forward_cases=2,
        resume=True,
    )
    assert resumed == summary_path

    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    saved["result"]["model_forward_simulation"]["completed_paths"] = 99
    checkpoint.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(ResearchReplayError) as error:
        run_checkpointed_research(
            inputs,
            config,
            output_root=output_root,
            run_id="resume-test-run",
            mode="model-forward",
            domain_names=(domain.name,),
            forward_cases=2,
            resume=True,
        )
    assert error.value.code == "checkpoint_integrity_mismatch"

    saved["result"]["model_forward_simulation"]["completed_paths"] = 99
    saved["result_sha256"] = replay._canonical_sha256(saved["result"])
    checkpoint.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(ResearchReplayError) as error:
        run_checkpointed_research(
            inputs,
            config,
            output_root=output_root,
            run_id="resume-test-run",
            mode="model-forward",
            domain_names=(domain.name,),
            forward_cases=2,
            resume=True,
        )
    assert error.value.code == "checkpoint_forward_accounting_invalid"


def test_checkpoint_run_rejects_resume_with_changed_config_hash(tmp_path):
    domain = make_domain(count=20)
    inputs = make_inputs(domain)
    config = make_research_config()
    output_root = tmp_path / "runs"
    output_root.mkdir()
    run_checkpointed_research(
        inputs,
        config,
        output_root=output_root,
        run_id="config-mismatch-run",
        mode="model-forward",
        domain_names=(domain.name,),
        forward_cases=1,
    )
    changed_config = ResearchCATConfig(config.envelope, config.cat, "e" * 64, config.content_sha256)
    with pytest.raises(ResearchReplayError) as error:
        run_checkpointed_research(
            inputs,
            changed_config,
            output_root=output_root,
            run_id="config-mismatch-run",
            mode="model-forward",
            domain_names=(domain.name,),
            forward_cases=1,
            resume=True,
        )
    assert error.value.code == "resume_identity_mismatch"


def test_partial_domain_checkpoint_resumes_without_recomputing_completed_domain(tmp_path, monkeypatch):
    first_domain = make_domain(count=20, name="First Domain")
    second_domain = make_domain(count=20, name="Second Domain")
    inputs = make_inputs(first_domain)
    inputs = replace(inputs, domains=(first_domain, second_domain))
    config = make_research_config()
    output_root = tmp_path / "runs"
    output_root.mkdir()
    original_build = replay._build_domain_result
    calls = []

    def fail_second_domain(run_inputs, domain, cat_config, **kwargs):
        calls.append(domain.name)
        if domain.name == second_domain.name:
            raise RuntimeError("simulated interruption after first aggregate checkpoint")
        return original_build(run_inputs, domain, cat_config, **kwargs)

    monkeypatch.setattr(replay, "_build_domain_result", fail_second_domain)
    with pytest.raises(RuntimeError):
        run_checkpointed_research(
            inputs,
            config,
            output_root=output_root,
            run_id="partial-resume-run",
            mode="model-forward",
            domain_names=(first_domain.name, second_domain.name),
            forward_cases=1,
        )
    assert calls == [first_domain.name, second_domain.name]
    assert (output_root / "partial-resume-run" / "checkpoints" / "first-domain.json").is_file()
    monkeypatch.setattr(replay, "_build_domain_result", original_build)

    summary_path = run_checkpointed_research(
        inputs,
        config,
        output_root=output_root,
        run_id="partial-resume-run",
        mode="model-forward",
        domain_names=(first_domain.name, second_domain.name),
        forward_cases=1,
        resume=True,
    )
    assert summary_path.is_file()
    summary = replay._read_json(summary_path, "test summary")
    assert set(summary["domains"]) == {first_domain.name, second_domain.name}
