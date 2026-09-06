from llm_runtime.domain.models import StreamEventType
from llm_runtime.providers.mock import MockProvider


def test_mock_provider_lifecycle_and_structured_generation(request_factory):
    provider = MockProvider(("mock-model",))
    request = request_factory(
        logical_model_id="mock-model",
        contract_model_id="MODEL_mock_test",
        structured_schema={"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}},
    )

    provider.load_model("mock-model")
    response = provider.generate(request)
    provider.unload_model("mock-model")

    assert response.structured == {"answer": "synthetic"}
    assert "mock-model" not in provider.loaded


def test_mock_stream_has_normalized_terminal_order(request_factory):
    provider = MockProvider(("mock-model",))
    request = request_factory(logical_model_id="mock-model", contract_model_id="MODEL_mock_test")

    events = list(provider.stream_generate(request))
    types = [event.event_type for event in events]

    assert types[0] is StreamEventType.START
    assert types[-2:] == [StreamEventType.USAGE, StreamEventType.DONE]
    assert not any(
        event.event_type is StreamEventType.DELTA
        for event in events[types.index(StreamEventType.DONE) + 1 :]
    )

