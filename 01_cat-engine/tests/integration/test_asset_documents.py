import asyncio
import json
import math
import threading
import time
from copy import deepcopy
from dataclasses import replace

import pytest
from test_management_api import CAT_BASE, asgi_request, make_runtime, summary

from cat_engine.api import assets, management
from cat_engine.api.app import CatRuntime, create_app


def template():
    runtime = CatRuntime()
    return {'bank_document': runtime.item_bank.to_dict(), 'config_document': runtime.config.to_dict()}


async def post(payload):
    return await asgi_request(create_app(), 'POST', '/internal/cat/management/validate-assets', payload)


async def simulate(payload, *, runtime=None):
    return await asgi_request(
        create_app(runtime=runtime), 'POST', f'{CAT_BASE}/simulate-assets', payload
    )


def test_actual_template_and_edited_document_do_not_change_runtime():
    import asyncio
    runtime = CatRuntime()
    before = deepcopy(runtime.item_bank.to_dict())
    payload = template()
    payload['bank_document']['items'][0]['stem'] = '合成工程题：本轮选择一个类别。'
    payload['bank_document']['status'] = 'draft'
    status, response = asyncio.run(post(payload))
    assert status == 200
    assert response['bank_document']['items'][0]['stem'] == payload['bank_document']['items'][0]['stem']
    assert response['item_count'] == 9
    assert runtime.item_bank.to_dict() == before and not runtime.sessions


@pytest.mark.parametrize('mutation', [
    lambda p: p['bank_document']['metadata'].update(synthetic=False),
    lambda p: p['bank_document']['metadata'].update(synthetic=1),
    lambda p: p['bank_document']['metadata'].update(psychological_interpretation_allowed=True),
    lambda p: p['bank_document']['metadata'].update(psychological_interpretation_allowed=0),
    lambda p: p['bank_document']['items'][0]['scoring'].update(never=0.0),
    lambda p: p['bank_document']['items'][0]['parameters'].update(a='1.0'),
    lambda p: p['bank_document']['items'][0]['parameters'].update(thresholds=[True,0,1,2]),
    lambda p: p['bank_document']['items'][0]['parameters'].update(thresholds=[2,1,0,-1]),
    lambda p: p['bank_document']['items'][1].update(item_id=p['bank_document']['items'][0]['item_id']),
    lambda p: p['config_document'].update(seed=True),
    lambda p: p['config_document'].update(max_items=10),
    lambda p: p['config_document'].update(prior_sd=-1),
    lambda p: p.update(subject_id='SUBJ_unexpected'),
])
def test_invalid_asset_documents_fail_closed(mutation):
    import asyncio
    payload = template()
    mutation(payload)
    assert asyncio.run(post(payload))[0] == 422


@pytest.mark.parametrize('n_examinees', [None, 99, 100.0, True, '100'])
def test_document_simulation_requires_a_strict_bounded_batch(n_examinees):
    payload = template()
    payload['n_examinees'] = n_examinees
    assert asyncio.run(simulate(payload))[0] == 422


def test_document_simulation_requires_batch_and_rejects_seed_overrides():
    payload = template()
    assert asyncio.run(simulate(payload))[0] == 422
    payload['n_examinees'] = 100
    payload['seed'] = 17
    assert asyncio.run(simulate(payload))[0] == 422


def test_document_simulation_rejects_draft_and_preserves_live_runtime():
    runtime = CatRuntime()
    bank_before = deepcopy(runtime.item_bank.to_dict())
    config_before = runtime.config
    payload = template()
    payload['n_examinees'] = 100
    payload['bank_document']['status'] = 'draft'

    status, body = asyncio.run(simulate(payload, runtime=runtime))

    assert status == 422
    assert body['detail'] == 'synthetic_cat_asset_invalid'
    assert runtime.item_bank.to_dict() == bank_before
    assert runtime.config == config_before
    assert runtime.sessions == {}


def test_document_simulation_returns_only_finite_aggregates(monkeypatch):
    runtime = CatRuntime()
    payload = template()
    payload['n_examinees'] = 100
    bank = runtime.item_bank
    config = runtime.config
    candidate = summary(runtime)
    monkeypatch.setattr(assets, '_run_assets_simulation', lambda _bank, _config, _n: candidate)

    status, body = asyncio.run(simulate(payload, runtime=runtime))

    assert status == 200
    assert body['engineering_only'] is True
    assert body['psychological_interpretation_allowed'] is False
    assert body['item_bank_id'] == bank.item_bank_id
    assert body['item_bank_version'] == bank.version
    assert body['config_version'] == config.config_version
    assert body['n_examinees'] == 100
    assert body['seed'] == config.seed
    assert set(body['metrics']) == {
        'bias', 'rmse', 'mae', 'mean_test_length', 'median_test_length', 'mean_se'
    }
    assert all(math.isfinite(value) for value in body['metrics'].values())
    assert sum(body['stopping_reason_distribution'].values()) == 100
    assert set(body) == {
        'engineering_only', 'psychological_interpretation_allowed', 'item_bank_id',
        'item_bank_version', 'config_version', 'n_examinees', 'seed', 'metrics',
        'stopping_reason_distribution'
    }
    assert 'results' not in json.dumps(body)
    assert runtime.sessions == {}


def test_document_simulation_validates_aggregate_identity_and_finiteness(monkeypatch):
    runtime = CatRuntime()
    payload = template()
    payload['n_examinees'] = 100
    baseline = summary(runtime)
    invalid = (
        replace(baseline, metadata={**baseline.metadata, 'config_version': 'wrong'}),
        replace(baseline, metrics={**baseline.metrics, 'rmse': math.inf}),
    )
    for candidate in invalid:
        monkeypatch.setattr(assets, '_run_assets_simulation', lambda _bank, _config, _n, value=candidate: value)
        status, body = asyncio.run(simulate(payload, runtime=runtime))
        assert status == 503
        assert body['detail'] == 'synthetic_cat_simulation_unavailable'


def test_document_simulation_shares_busy_gate_with_fixed_simulation(monkeypatch):
    runtime = make_runtime(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def blocked_document_simulation(_bank, _config, _n):
        started.set()
        assert release.wait(timeout=5)
        return summary(runtime)

    monkeypatch.setattr(assets, '_run_assets_simulation', blocked_document_simulation)
    payload = template()
    payload['n_examinees'] = 100
    app = create_app(runtime=runtime)

    async def exercise():
        first = asyncio.create_task(
            asgi_request(app, 'POST', f'{CAT_BASE}/simulate-assets', payload)
        )
        assert await asyncio.to_thread(started.wait, 5)
        busy = await asgi_request(app, 'POST', f'{CAT_BASE}/simulations', {})
        release.set()
        return await first, busy

    try:
        first, busy = asyncio.run(exercise())
    finally:
        release.set()

    assert first[0] == 200
    assert busy[0] == 409
    assert busy[1]['detail'] == 'synthetic_cat_simulation_busy'


def test_cancelled_document_simulation_keeps_shared_gate_until_worker_finishes(monkeypatch):
    runtime = make_runtime(monkeypatch)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    loop_errors = []

    def failing_document_simulation(_bank, _config, _n):
        started.set()
        try:
            assert release.wait(timeout=5)
            raise RuntimeError('synthetic simulation failure')
        finally:
            finished.set()

    monkeypatch.setattr(assets, '_run_assets_simulation', failing_document_simulation)
    monkeypatch.setattr(management, '_run_simulation', lambda _runtime, _n: summary(runtime))
    payload = template()
    payload['n_examinees'] = 100
    app = create_app(runtime=runtime)

    async def exercise():
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
        try:
            first_task = asyncio.create_task(
                asgi_request(app, 'POST', f'{CAT_BASE}/simulate-assets', payload)
            )
            assert await asyncio.to_thread(started.wait, 5)
            first_task.cancel()
            try:
                await first_task
            except asyncio.CancelledError:
                pass
            busy = await asgi_request(app, 'POST', f'{CAT_BASE}/simulations', {})
            release.set()
            assert await asyncio.to_thread(finished.wait, 5)
            recovered = (409, {})
            for _ in range(100):
                await asyncio.sleep(0.01)
                recovered = await asgi_request(app, 'POST', f'{CAT_BASE}/simulations', {})
                if recovered[0] != 409:
                    break
            return busy, recovered
        finally:
            release.set()
            loop.set_exception_handler(previous_handler)

    busy, recovered = asyncio.run(exercise())
    assert busy[0] == 409
    assert recovered[0] == 200
    assert finished.is_set()
    assert loop_errors == []


def test_real_document_simulation_repeats_and_uses_changed_saved_config():
    runtime = CatRuntime()
    bank_document = runtime.item_bank.to_dict()
    config_document = runtime.config.to_dict()
    payload = {
        'bank_document': bank_document,
        'config_document': config_document,
        'n_examinees': 100,
    }
    wall_start = time.perf_counter()
    first_status, first = asyncio.run(simulate(payload, runtime=runtime))
    first_wall = time.perf_counter() - wall_start
    wall_start = time.perf_counter()
    second_status, second = asyncio.run(simulate(payload, runtime=runtime))
    second_wall = time.perf_counter() - wall_start

    changed_config = {**config_document, 'config_version': 'qa.max3.v1', 'max_items': 3}
    changed_payload = {**payload, 'config_document': changed_config}
    wall_start = time.perf_counter()
    changed_status, changed = asyncio.run(simulate(changed_payload, runtime=runtime))
    changed_wall = time.perf_counter() - wall_start
    print(
        'CAT_ASSET_SIM_N100 '
        f'repeat1_wall_seconds={first_wall:.3f} '
        f'repeat2_wall_seconds={second_wall:.3f} '
        f'changed_config_wall_seconds={changed_wall:.3f}'
    )

    assert first_status == second_status == changed_status == 200
    assert first == second
    assert first['item_bank_id'] == bank_document['item_bank_id']
    assert first['item_bank_version'] == bank_document['version']
    assert first['config_version'] == config_document['config_version']
    assert first['seed'] == config_document['seed']
    assert changed['config_version'] == 'qa.max3.v1'
    assert changed['metrics']['mean_test_length'] == 3.0
    assert first['metrics']['mean_test_length'] > changed['metrics']['mean_test_length']
    assert runtime.item_bank.to_dict() == bank_document
    assert runtime.config.to_dict() == config_document
    assert runtime.sessions == {}
