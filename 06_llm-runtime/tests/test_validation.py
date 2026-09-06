from __future__ import annotations

import pytest

from llm_runtime.errors import LLMRuntimeError, RuntimeErrorCode
from llm_runtime.validation import parse_and_validate


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string", "minLength": 1}},
}


def test_structured_output_requires_schema_semantics():
    assert parse_and_validate('{"answer":"OK"}', SCHEMA) == {"answer": "OK"}


@pytest.mark.parametrize("value", ["not json", '{"answer": 1}', '{"answer":""}'])
def test_invalid_structured_output_is_stable_error(value):
    with pytest.raises(LLMRuntimeError) as caught:
        parse_and_validate(value, SCHEMA)
    assert caught.value.code is RuntimeErrorCode.INVALID_STRUCTURED_OUTPUT

