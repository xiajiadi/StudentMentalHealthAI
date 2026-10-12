"""Unit/API checks for synthetic-only CAT management routes (no live server)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import math
from pathlib import Path
import threading
import time

import cat_engine.api.management as management
from cat_engine.api.app import CatRuntime, create_app
from cat_engine.simulation.models import SimulationSummary


CAT_ROOT = Path(__file__).resolve().parents[2]
CAT_BASE = "/internal/cat/management"


async def asgi_request(app, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    request_message = {"type": "http.request", "body": body, "more_body": False}
    messages: list[dict] = []
    received = False

    async def receive() -> dict:
        nonlocal received
        if not received:
            received = True
            return request_message
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    headers = [(b"host", b"testserver")]
    if payload is not None:
        headers.append((b"content-type", b"application/json"))
    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        },
        receive,
        send,
    )
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return status, json.loads(response_body or b"{}")


def request(app, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    return asyncio.run(asgi_request(app, method, path, payload))


def make_runtime(monkeypatch) -> CatRuntime:
    monkeypatch.setenv("SMHAI_CAT_CONFIG", str(CAT_ROOT / "fixtures" / "demo_cat_config.v1.json"))
    monkeypatch.setenv("SMHAI_CAT_ITEM_BANK", str(CAT_ROOT / "fixtures" / "synthetic_item_bank.v1.json"))
    return CatRuntime()


def summary(runtime: CatRuntime, n_examinees: int = 100) -> SimulationSummary:
    return SimulationSummary(
        n_examinees=n_examinees,
        seed=runtime.config.seed or 0,
        metadata={
            "item_bank_id": runtime.item_bank.item_bank_id,
            "item_bank_version": runtime.item_bank.version,
            "config_version": runtime.config.config_version,
        },
        metrics={
            "bias": 0.1,
            "rmse": 0.2,
            "mae": 0.15,
            "mean_test_length": 6.0,
            "median_test_length": 6.0,
            "mean_se": 0.5,
        },
        stopping_reason_distribution={"MAX_ITEMS_REACHED": n_examinees},
        results=(),
    )


def test_catalog_returns_only_safe_current_fixture_metadata(monkeypatch) -> None:
    runtime = make_runtime(monkeypatch)
    status, body = request(create_app(runtime=runtime), "GET", f"{CAT_BASE}/catalog")

    assert status == 200
    assert body == {
        "schema_version": "synthetic_cat_management.v1",
        "engineering_only": True,
        "psychological_interpretation_allowed": False,
        "item_bank": {
            "item_bank_id": runtime.item_bank.item_bank_id,
            "version": runtime.item_bank.version,
            "instrument_id": runtime.item_bank.instrument_id,
            "item_count": len(runtime.item_bank.items),
            "dimension_count": len(runtime.item_bank.dimensions),
            "status": "published",
            "validation": "STRUCTURE_VALID",
        },
        "config": {
            "config_version": runtime.config.config_version,
            "model": runtime.config.model,
            "estimator": runtime.config.estimator,
            "selection_method": runtime.config.selection_method,
            "min_items": runtime.config.min_items,
            "max_items": runtime.config.max_items,
            "se_threshold": runtime.config.se_threshold,
            "seed": runtime.config.seed,
        },
        "simulation": {"available": True, "sample_sizes": [100, 1000], "fixed_seed": runtime.config.seed},
    }
    body_text = json.dumps(body)
    assert "parameters" not in body_text
    assert "thresholds" not in body_text
    assert "results" not in body_text
    assert str(runtime.bank_path) not in body_text


def test_catalog_and_simulation_fail_closed_for_non_synthetic_runtime(monkeypatch) -> None:
    runtime = make_runtime(monkeypatch)
    runtime.item_bank.metadata["synthetic"] = False
    app = create_app(runtime=runtime)
    catalog_status, _ = request(app, "GET", f"{CAT_BASE}/catalog")
    simulation_status, _ = request(app, "POST", f"{CAT_BASE}/simulations", {})

    assert catalog_status == 503
    assert simulation_status == 503
    assert runtime.sessions == {}


def test_simulation_request_accepts_only_bounded_sizes_without_overrides(monkeypatch) -> None:
    runtime = make_runtime(monkeypatch)
    app = create_app(runtime=runtime)
    rejected_size, _ = request(app, "POST", f"{CAT_BASE}/simulations", {"n_examinees": 999})
    rejected_seed, _ = request(app, "POST", f"{CAT_BASE}/simulations", {"n_examinees": 100, "seed": 7})
    rejected_string, _ = request(app, "POST", f"{CAT_BASE}/simulations", {"n_examinees": "100"})
    rejected_float, _ = request(app, "POST", f"{CAT_BASE}/simulations", {"n_examinees": 100.0})
    rejected_bool, _ = request(app, "POST", f"{CAT_BASE}/simulations", {"n_examinees": True})

    assert rejected_size == 422
    assert rejected_seed == 422
    assert rejected_string == 422
    assert rejected_float == 422
    assert rejected_bool == 422
    assert runtime.sessions == {}


def test_catalog_fails_closed_when_config_no_longer_validates(monkeypatch) -> None:
    runtime = make_runtime(monkeypatch)
    runtime.config = replace(runtime.config, max_items=0)
    status, body = request(create_app(runtime=runtime), "GET", f"{CAT_BASE}/catalog")
    assert status == 503
    assert body["detail"] == "synthetic_cat_management_unavailable"


def test_simulation_projects_aggregates_only_and_repeats_with_fixed_seed(monkeypatch) -> None:
    runtime = make_runtime(monkeypatch)

    def simulated(n_examinees: int) -> SimulationSummary:
        return summary(runtime, n_examinees)

    monkeypatch.setattr(management, "_run_simulation", lambda _runtime, n: simulated(n))
    app = create_app(runtime=runtime)
    first_status, first = request(app, "POST", f"{CAT_BASE}/simulations", {})
    second_status, second = request(app, "POST", f"{CAT_BASE}/simulations", {"n_examinees": 100})

    assert first_status == second_status == 200
    assert first == second
    body = first
    assert body["schema_version"] == "synthetic_cat_management.v1"
    assert body["engineering_only"] is True
    assert body["psychological_interpretation_allowed"] is False
    assert body["item_bank_id"] == runtime.item_bank.item_bank_id
    assert body["item_bank_version"] == runtime.item_bank.version
    assert body["config_version"] == runtime.config.config_version
    assert body["n_examinees"] == 100
    assert body["seed"] == runtime.config.seed
    assert set(body["metrics"]) == {"bias", "rmse", "mae", "mean_test_length", "median_test_length", "mean_se"}
    assert all(math.isfinite(value) for value in body["metrics"].values())
    assert sum(body["stopping_reason_distribution"].values()) == 100
    assert "results" not in body
    response_text = json.dumps(first)
    assert "examinee_id" not in response_text
    assert "subject_id" not in response_text
    assert "parameters" not in response_text
    assert str(runtime.bank_path) not in response_text
    assert runtime.sessions == {}


def test_real_provider_runs_bounded_batch_and_is_repeatable_without_live_sessions(monkeypatch) -> None:
    runtime = make_runtime(monkeypatch)
    app = create_app(runtime=runtime)
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    first_status, first = request(app, "POST", f"{CAT_BASE}/simulations", {"n_examinees": 100})
    first_wall = time.perf_counter() - wall_start
    first_cpu = time.process_time() - cpu_start

    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    second_status, second = request(app, "POST", f"{CAT_BASE}/simulations", {"n_examinees": 100})
    second_wall = time.perf_counter() - wall_start
    second_cpu = time.process_time() - cpu_start

    print(f"CAT_MANAGEMENT_N100_RUN1 wall_seconds={first_wall:.3f} process_cpu_seconds={first_cpu:.3f}")
    print(f"CAT_MANAGEMENT_N100_RUN2 wall_seconds={second_wall:.3f} process_cpu_seconds={second_cpu:.3f}")
    assert first_status == second_status == 200
    assert first == second
    assert first["n_examinees"] == 100
    assert sum(first["stopping_reason_distribution"].values()) == 100
    assert runtime.sessions == {}


def test_simulation_rejects_non_finite_metrics_and_inconsistent_stop_counts(monkeypatch) -> None:
    runtime = make_runtime(monkeypatch)
    baseline = summary(runtime)
    invalid = (
        replace(baseline, metrics={**baseline.metrics, "rmse": math.nan}),
        replace(baseline, stopping_reason_distribution={"MAX_ITEMS_REACHED": 99}),
    )
    app = create_app(runtime=runtime)
    for candidate in invalid:
        monkeypatch.setattr(management, "_run_simulation", lambda _runtime, _n, value=candidate: value)
        status, body = request(app, "POST", f"{CAT_BASE}/simulations", {})
        assert status == 503
        assert body["detail"] == "synthetic_cat_simulation_unavailable"


def test_only_one_simulation_runs_at_a_time(monkeypatch) -> None:
    runtime = make_runtime(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def blocked_simulation(_runtime: CatRuntime, n_examinees: int) -> SimulationSummary:
        started.set()
        assert release.wait(timeout=5)
        return summary(runtime, n_examinees)

    monkeypatch.setattr(management, "_run_simulation", blocked_simulation)
    app = create_app(runtime=runtime)
    async def concurrent_requests() -> tuple[tuple[int, dict], tuple[int, dict]]:
        first_request = asyncio.create_task(asgi_request(app, "POST", f"{CAT_BASE}/simulations", {}))
        assert await asyncio.to_thread(started.wait, 5)
        second = await asgi_request(app, "POST", f"{CAT_BASE}/simulations", {})
        release.set()
        return await first_request, second

    try:
        first, second = asyncio.run(concurrent_requests())
    finally:
        release.set()

    assert first[0] == 200
    assert second[0] == 409
    assert second[1]["detail"] == "synthetic_cat_simulation_busy"


def test_cancelled_request_keeps_mutex_until_failed_worker_finishes(monkeypatch) -> None:
    runtime = make_runtime(monkeypatch)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    attempts = 0

    def failing_simulation(_runtime: CatRuntime, _n_examinees: int) -> SimulationSummary:
        nonlocal attempts
        attempts += 1
        started.set()
        try:
            assert release.wait(timeout=5)
            raise RuntimeError("synthetic simulation failure")
        finally:
            finished.set()

    monkeypatch.setattr(management, "_run_simulation", failing_simulation)
    app = create_app(runtime=runtime)

    async def exercise_cancelled_request() -> tuple[tuple[int, dict], tuple[int, dict], list[dict]]:
        loop = asyncio.get_running_loop()
        loop_errors: list[dict] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
        try:
            first_task = asyncio.create_task(asgi_request(app, "POST", f"{CAT_BASE}/simulations", {}))
            assert await asyncio.to_thread(started.wait, 5)
            first_task.cancel()
            try:
                await first_task
            except asyncio.CancelledError:
                pass

            busy = await asgi_request(app, "POST", f"{CAT_BASE}/simulations", {})
            release.set()
            assert await asyncio.to_thread(finished.wait, 5)

            recovered = (503, {})
            for _ in range(100):
                await asyncio.sleep(0.01)
                recovered = await asgi_request(app, "POST", f"{CAT_BASE}/simulations", {})
                if recovered[0] != 409:
                    break
            return busy, recovered, loop_errors
        finally:
            release.set()
            loop.set_exception_handler(previous_handler)

    busy, recovered, loop_errors = asyncio.run(exercise_cancelled_request())
    assert busy[0] == 409
    assert recovered[0] == 503
    assert recovered[1]["detail"] == "synthetic_cat_simulation_unavailable"
    assert attempts == 2
    assert finished.is_set()
    assert loop_errors == []
