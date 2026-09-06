from __future__ import annotations

import threading

from llm_runtime.domain.models import StreamEventType
from llm_runtime.providers.http import ActiveHTTPStream
from llm_runtime.providers.ollama import OllamaProvider


class FakeResponse:
    def __init__(self, lines):
        self.lines = [line.encode("utf-8") for line in lines]
        self.closed = False

    def __iter__(self):
        return iter(self.lines)

    def close(self):
        self.closed = True


class FakeHTTP:
    def __init__(self):
        self.payloads = []
        self.responses = {
            ("GET", "/api/tags"): {
                "models": [
                    {
                        "name": "qwen2.5:0.5b",
                        "model": "qwen2.5:0.5b",
                        "digest": "sha256:test",
                        "size": 398_000_000,
                        "details": {"format": "gguf", "family": "qwen2", "quantization_level": "Q8_0"},
                    }
                ]
            },
            ("POST", "/api/generate"): {
                "response": '{"answer":"OK"}',
                "done": True,
                "prompt_eval_count": 3,
                "eval_count": 2,
                "done_reason": "stop",
            },
            ("POST", "/api/chat"): {
                "message": {"role": "assistant", "content": '{"answer":"OK"}'},
                "done": True,
                "prompt_eval_count": 3,
                "eval_count": 2,
                "done_reason": "stop",
            },
            ("GET", "/api/ps"): {"models": []},
        }

    def request_json(self, method, path, payload=None, *, timeout):
        self.payloads.append((method, path, payload))
        return self.responses[(method, path)]

    def open_stream(self, method, path, payload, *, timeout, request_id):
        self.payloads.append((method, path, payload))
        response = FakeResponse([
            '{"response":"O","done":false}',
            '{"response":"K","done":false}',
            '{"response":"","done":true,"prompt_eval_count":3,"eval_count":2,"done_reason":"stop"}',
        ])
        return ActiveHTTPStream(response=response, cancel_event=threading.Event())

    def close_stream(self, request_id, active):
        active.response.close()

    def cancel(self, request_id):
        return False


def test_ollama_discovery_normalizes_metadata():
    provider = OllamaProvider()
    provider.http = FakeHTTP()
    models = provider.discover_models()

    assert models[0]["provider_model_id"] == "qwen2.5:0.5b"
    assert models[0]["quantization"] == "Q8_0"
    assert models[0]["digest"] == "sha256:test"


def test_ollama_generation_uses_native_schema_format(request_factory):
    provider = OllamaProvider()
    fake = FakeHTTP()
    provider.http = fake
    request = request_factory(
        logical_model_id="qwen2.5-0.5b-engineering",
        provider_model_id="qwen2.5:0.5b",
        structured_schema={"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}},
    )

    response = provider.generate(request)
    payload = fake.payloads[-1][2]
    assert response.structured == {"answer": "OK"}
    assert payload["model"] == "qwen2.5:0.5b"
    assert payload["format"]["required"] == ["answer"]
    assert payload["stream"] is False


def test_ollama_stream_normalizes_ndjson_order(request_factory):
    provider = OllamaProvider()
    provider.http = FakeHTTP()
    request = request_factory(provider_model_id="qwen2.5:0.5b")

    events = list(provider.stream_generate(request))
    types = [event.event_type for event in events]

    assert types == [StreamEventType.START, StreamEventType.DELTA, StreamEventType.DELTA, StreamEventType.USAGE, StreamEventType.DONE]
    assert "O" + "K" == "".join(event.delta for event in events if event.event_type is StreamEventType.DELTA)


def test_ollama_chat_messages_stay_inside_provider_adapter(request_factory):
    provider = OllamaProvider()
    fake = FakeHTTP()
    provider.http = fake
    request = request_factory(
        prompt="",
        messages=({"role": "user", "content": "Reply with JSON."},),
        structured_schema={
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
    )

    response = provider.generate(request)

    assert response.structured == {"answer": "OK"}
    method, path, payload = fake.payloads[-1]
    assert (method, path) == ("POST", "/api/chat")
    assert payload["messages"] == [{"role": "user", "content": "Reply with JSON."}]
    assert "prompt" not in payload
