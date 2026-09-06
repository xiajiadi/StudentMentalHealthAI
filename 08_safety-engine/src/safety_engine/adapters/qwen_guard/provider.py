"""Pinned local Qwen3Guard-Gen provider.

The provider is lazy and CPU-compatible.  Its raw generated text is returned
only in the transient adapter result for the synthetic evaluation harness; it
is never placed in ``SafetySignal`` or ``SafetyTrace``.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from safety_engine.adapters.base import AdapterResult
from safety_engine.domain import (
    ComponentHealth,
    ErrorCode,
    SafetyError,
    SafetySignal,
    SeverityHint,
    SignalSource,
    SignalType,
)

DEFAULT_MODEL = "Qwen/Qwen3Guard-Gen-0.6B"
DEFAULT_REVISION = "fada3b2f655b89601929198343c94cd2f64d93cc"


@dataclass(slots=True, frozen=True)
class QwenParsedOutput:
    label: str
    categories: tuple[str, ...]
    refusal: str | None
    raw_output: str


class Qwen3GuardProvider:
    component = "qwen3guard"

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL,
        revision: str = DEFAULT_REVISION,
        cache_dir: str | Path | None = None,
        device: str = "cpu",
        max_new_tokens: int = 128,
    ) -> None:
        self.model_name = model_name
        self.revision = revision
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.device = device
        self.max_new_tokens = max_new_tokens
        self.version = revision
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None
        self._load_error: str | None = None
        self.load_time_ms: float | None = None
        self.last_inference_ms: float | None = None

    def load(self) -> ComponentHealth:
        """Load the pinned local checkpoint and return its readiness state."""

        try:
            self._ensure_loaded()
        except SafetyError as exc:
            return ComponentHealth(
                component=self.component,
                available=False,
                ready=False,
                version=self.version,
                detail_code=exc.code.value,
            )
        return self.health()

    def model_info(self) -> dict[str, Any]:
        dtype = None
        if self._model is not None:
            try:
                dtype = str(next(self._model.parameters()).dtype).removeprefix("torch.")
            except (StopIteration, AttributeError):
                dtype = None
        return {
            "name": self.model_name,
            "revision": self.revision,
            "device": self.device,
            "dtype": dtype,
            "loaded": self._model is not None and self._tokenizer is not None,
            "chat_template_loaded": bool(getattr(self._tokenizer, "chat_template", None)),
        }

    def capabilities(self) -> dict[str, Any]:
        return {
            "input_classification": True,
            "output_classification": True,
            "streaming": False,
            "stream_status": "DEFERRED_ROUND_2_GPU",
        }

    def _ensure_loaded(self) -> tuple[Any, Any, Any]:
        if self._tokenizer is not None and self._model is not None and self._torch is not None:
            return self._tokenizer, self._model, self._torch
        started = time.perf_counter()
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except Exception as exc:  # pragma: no cover - optional runtime dependency
            self._load_error = f"{type(exc).__name__}: {exc}"
            raise SafetyError(
                ErrorCode.GUARD_MODEL_UNAVAILABLE,
                "Qwen3Guard runtime is not available",
                details={"model": self.model_name},
            ) from exc
        try:
            tokenizer_kwargs: dict[str, Any] = {
                "revision": self.revision,
                "trust_remote_code": True,
                "local_files_only": True,
            }
            model_kwargs: dict[str, Any] = {
                "revision": self.revision,
                "trust_remote_code": True,
                "local_files_only": True,
                "torch_dtype": torch.float32,
            }
            if self.cache_dir:
                tokenizer_kwargs["cache_dir"] = str(self.cache_dir)
                model_kwargs["cache_dir"] = str(self.cache_dir)
            tokenizer = AutoTokenizer.from_pretrained(self.model_name, **tokenizer_kwargs)
            model: Any = AutoModelForCausalLM.from_pretrained(self.model_name, **model_kwargs)
            model.to(self.device)
            model.eval()
        except Exception as exc:
            self._load_error = f"{type(exc).__name__}: {exc}"
            raise SafetyError(
                ErrorCode.GUARD_MODEL_UNAVAILABLE,
                "Qwen3Guard model could not be loaded",
                details={"model": self.model_name, "revision": self.revision},
            ) from exc
        self._tokenizer = tokenizer
        self._model = model
        self._torch = torch
        self.load_time_ms = (time.perf_counter() - started) * 1000
        return tokenizer, model, torch

    def health(self) -> ComponentHealth:
        package_version = _package_version("transformers", None)
        if self._model is None:
            if package_version is None:
                return ComponentHealth(
                    component=self.component,
                    available=False,
                    ready=False,
                    version=self.version,
                    detail_code=ErrorCode.GUARD_MODEL_UNAVAILABLE.value,
                )
            return ComponentHealth(
                component=self.component,
                available=True,
                ready=False,
                version=self.version,
                detail_code="MODEL_NOT_LOADED",
            )
        return ComponentHealth(
            component=self.component,
            available=True,
            ready=True,
            version=self.version,
            latency_ms=self.last_inference_ms,
        )

    async def classify_input(self, text: str, *, trace_id: str) -> AdapterResult:
        return await asyncio.to_thread(self._classify_and_signal, text, trace_id, "input")

    async def classify_response(
        self, user_message: str, candidate: str, *, trace_id: str
    ) -> AdapterResult:
        return await asyncio.to_thread(
            self._classify_response_and_signal, user_message, candidate, trace_id
        )

    async def classify_output(
        self, user_message: str, candidate: str, *, trace_id: str
    ) -> AdapterResult:
        return await self.classify_response(user_message, candidate, trace_id=trace_id)

    def classify_for_evaluation(self, text: str, *, trace_id: str) -> AdapterResult:
        """Synchronous hook used by the CPU evaluation harness."""

        return self._classify_and_signal(text, trace_id, "input")

    def _classify_and_signal(self, text: str, trace_id: str, route: str) -> AdapterResult:
        messages = [{"role": "user", "content": text}]
        parsed, inference_ms = self._run(messages)
        return self._to_result(parsed, trace_id=trace_id, route=route, inference_ms=inference_ms)

    def _classify_response_and_signal(
        self, user_message: str, candidate: str, trace_id: str
    ) -> AdapterResult:
        messages = [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": candidate},
        ]
        parsed, inference_ms = self._run(messages)
        return self._to_result(
            parsed, trace_id=trace_id, route="response", inference_ms=inference_ms
        )

    def _run(self, messages: list[dict[str, str]]) -> tuple[QwenParsedOutput, float]:
        tokenizer, model, torch = self._ensure_loaded()
        try:
            prompt = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = tokenizer(prompt, return_tensors="pt")
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            started = time.perf_counter()
            with torch.inference_mode():
                generated = model.generate(
                    **inputs,
                    max_new_tokens=self.max_new_tokens,
                    do_sample=False,
                    pad_token_id=tokenizer.eos_token_id,
                )
            input_length = inputs["input_ids"].shape[1]
            output_tokens = generated[0][input_length:]
            raw_output = tokenizer.decode(output_tokens, skip_special_tokens=True).strip()
            inference_ms = (time.perf_counter() - started) * 1000
            self.last_inference_ms = inference_ms
        except Exception as exc:
            raise SafetyError(
                ErrorCode.GUARD_MODEL_UNAVAILABLE,
                "Qwen3Guard inference failed",
                details={"model": self.model_name},
            ) from exc
        return _parse_output(raw_output), inference_ms

    def _to_result(
        self,
        parsed: QwenParsedOutput,
        *,
        trace_id: str,
        route: str,
        inference_ms: float,
    ) -> AdapterResult:
        label = parsed.label
        if label == "Safe":
            reason_code = "CONTENT_SAFE"
            severity = SeverityHint.LOW
            status = "PASSED"
        elif label == "Controversial":
            reason_code = "CONTENT_CONTROVERSIAL"
            severity = SeverityHint.MODERATE
            status = "REVIEW_REQUIRED"
        else:
            reason_code = "CONTENT_UNSAFE"
            severity = SeverityHint.HIGH
            status = "BLOCKED"
        signal = SafetySignal(
            source=SignalSource.QWEN3GUARD,
            signal_type=SignalType.CONTENT,
            category="qwen3guard",
            severity_hint=severity,
            confidence=None,
            reason_code=reason_code,
            component=self.component,
            component_version=self.version,
            trace_id=trace_id,
            metadata={
                "label": label,
                "categories": list(parsed.categories),
                "refusal": parsed.refusal,
                "route": route,
                "inference_latency_ms": round(inference_ms, 3),
                "raw_output_digest": hashlib.sha256(parsed.raw_output.encode("utf-8")).hexdigest(),
                "raw_output_length": len(parsed.raw_output),
            },
        )
        return AdapterResult(
            status=status,
            signals=[signal],
            metadata={
                "label": label,
                "categories": list(parsed.categories),
                "refusal": parsed.refusal,
                "raw_output": parsed.raw_output,
                "inference_latency_ms": inference_ms,
                "model": self.model_name,
                "revision": self.revision,
            },
        )


def _parse_output(raw_output: str) -> QwenParsedOutput:
    safety_match = re.search(r"Safety\s*:\s*(Safe|Unsafe|Controversial)\b", raw_output, re.I)
    if not safety_match:
        raise SafetyError(
            ErrorCode.GUARD_MODEL_UNAVAILABLE,
            "Qwen3Guard returned an unparseable safety label",
            details={"output_digest": hashlib.sha256(raw_output.encode("utf-8")).hexdigest()},
        )
    label = safety_match.group(1).capitalize()
    categories_match = re.search(r"(?:Categories?|Category)\s*:\s*(.+?)(?:\n|$)", raw_output, re.I)
    categories: tuple[str, ...] = ()
    if categories_match:
        categories = tuple(
            item.strip(" `-.,")
            for item in re.split(r",|;|\|", categories_match.group(1))
            if item.strip(" `-.,")
        )
    refusal_match = re.search(r"Refusal\s*:\s*(Yes|No)\b", raw_output, re.I)
    refusal = refusal_match.group(1).capitalize() if refusal_match else None
    return QwenParsedOutput(
        label=label, categories=categories, refusal=refusal, raw_output=raw_output
    )


def _package_version(package: str, fallback: str | None) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return fallback
