from copy import deepcopy

import pytest
from cat_engine.api.app import CatRuntime, create_app
from test_management_api import asgi_request


def template():
    runtime = CatRuntime()
    return {'bank_document': runtime.item_bank.to_dict(), 'config_document': runtime.config.to_dict()}


async def post(payload):
    return await asgi_request(create_app(), 'POST', '/internal/cat/management/validate-assets', payload)


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
    lambda p: p['bank_document']['metadata'].update(psychological_interpretation_allowed=True),
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
