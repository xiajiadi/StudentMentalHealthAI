from llm_runtime.errors import RuntimeErrorCode, map_http_error, map_provider_error


def test_ollama_model_not_found_mapping():
    error = map_http_error(404, {"error": "model qwen2.5:0.5b not found"}, provider="ollama")
    assert error.code is RuntimeErrorCode.MODEL_NOT_FOUND
    assert error.retryable is False


def test_transient_provider_error_is_retryable():
    error = map_http_error(503, {"error": "loading model"}, provider="ollama")
    assert error.code is RuntimeErrorCode.PROVIDER_NOT_READY
    assert error.retryable is True


def test_llama_out_of_memory_mapping():
    error = map_provider_error("CUDA out of memory", provider="llama.cpp")
    assert error.code is RuntimeErrorCode.OUT_OF_MEMORY
    assert error.retryable is False

