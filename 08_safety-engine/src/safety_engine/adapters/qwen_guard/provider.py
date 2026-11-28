"""Pinned local Qwen3Guard-Gen provider.

The provider is lazy and CPU-compatible.  Its raw generated text is returned
only in the transient adapter result for the synthetic evaluation harness; it
is never placed in ``SafetySignal`` or ``SafetyTrace``.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
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
_LOGGER = logging.getLogger(__name__)


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
        accelerate_cpu: bool = False,
        serialize_cpu_checks: bool = False,
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
        self._accelerate_cpu = (
            accelerate_cpu and model_name == DEFAULT_MODEL
            and revision == DEFAULT_REVISION and device == "cpu"
        )
        self._fixed_prefixes: dict[str, tuple[Any, Any, tuple[int, ...]]] = {}
        # Each inference already uses the service's configured CPU threads.
        self._executor = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="qwen-safety")
            if serialize_cpu_checks and device == "cpu" else None
        )

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)

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
        if self._accelerate_cpu:
            try:
                with torch.inference_mode():
                    self._fixed_prefixes = self._build_fixed_prefixes(tokenizer, model)
            except Exception:
                _LOGGER.warning("Fixed guard prompt acceleration unavailable")
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
        return await self._submit(self._classify_and_signal, text, trace_id, "input")

    async def classify_response(
        self, user_message: str, candidate: str, *, trace_id: str
    ) -> AdapterResult:
        return await self._submit(
            self._classify_response_and_signal, user_message, candidate, trace_id
        )

    async def _submit(self, classify: Callable[..., AdapterResult], *args: str) -> AdapterResult:
        if self._executor is None:
            return await asyncio.to_thread(classify, *args)
        return await asyncio.get_running_loop().run_in_executor(self._executor, classify, *args)

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
                output_tokens = self._decode(
                    inputs, messages[-1]["role"], tokenizer, model, torch
                )
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

    def _build_fixed_prefixes(self, tokenizer: Any, model: Any) -> dict:
        result = {}
        for role in ("user", "assistant"):
            inputs = []
            for sample in ("apple", "乙"):
                messages = [{"role": "user", "content": sample}]
                if role == "assistant":
                    messages.append({"role": "assistant", "content": sample})
                rendered = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
                inputs.append(tokenizer(rendered, return_tensors="pt").input_ids)
            common = 0
            for left, right in zip(inputs[0][0].tolist(), inputs[1][0].tolist()):
                if left != right:
                    break
                common += 1
            prefix = inputs[0][:, :common]
            if common < 2:
                continue
            draft = "Safety: Safe\nCategories: None"
            if role == "assistant":
                draft += "\nRefusal: No"
            # Only these fixed policy tokens can survive between requests.
            cache = model.model(input_ids=prefix, use_cache=True).past_key_values
            result[role] = (prefix, cache, tuple(tokenizer.encode(draft + "\n", add_special_tokens=False)))
        return result

    def _decode(self, inputs: dict, role: str, tokenizer: Any, model: Any, torch: Any) -> Any:
        full_ids = inputs["input_ids"]
        fixed = self._fixed_prefixes.get(role)
        if fixed is not None:
            prefix, cache, draft = fixed
            prefix_length = prefix.shape[1]
            if full_ids.shape[1] > prefix_length and torch.equal(full_ids[:, :prefix_length], prefix):
                try:
                    return self._decode_cached(full_ids, inputs, cache, draft, tokenizer, model, torch)
                except Exception:
                    _LOGGER.warning("Fixed guard prompt verification failed, using full inference")
        return model.generate(
            **inputs, max_new_tokens=self.max_new_tokens,
            do_sample=False, pad_token_id=tokenizer.eos_token_id,
        )[0, full_ids.shape[1]:]

    def _decode_cached(
        self, full_ids: Any, inputs: dict, cache: Any, draft: tuple[int, ...],
        tokenizer: Any, model: Any, torch: Any,
    ) -> Any:
        eos = model.generation_config.eos_token_id
        end_tokens = {eos} if isinstance(eos, int) else set(eos)
        if self.max_new_tokens > len(draft):
            suffix = torch.tensor([draft], dtype=full_ids.dtype)
            with_draft = torch.cat((full_ids[:, cache.get_seq_length():], suffix), dim=1)
            checked_cache = deepcopy(cache)
            predictions = model(
                input_ids=with_draft, past_key_values=checked_cache, use_cache=True,
                logits_to_keep=len(draft) + 1,
            ).logits[0].argmax(dim=-1).tolist()
            for index, token in enumerate(predictions):
                if token in end_tokens:
                    return list(draft[:index])
                if index >= len(draft) or token != draft[index]:
                    # The first divergence is also a verified greedy token.
                    # Reuse only the cache through the accepted token prefix.
                    unaccepted = len(draft) - index
                    if unaccepted:
                        checked_cache.crop(-unaccepted)
                    accepted = torch.tensor([(*draft[:index], token)], dtype=full_ids.dtype)
                    remaining = self.max_new_tokens - accepted.shape[1]
                    if remaining <= 0:
                        return accepted[0]
                    expanded = torch.cat((full_ids, accepted), dim=1)
                    mask = torch.cat((inputs["attention_mask"], torch.ones_like(accepted)), dim=1)
                    return model.generate(
                        input_ids=expanded, attention_mask=mask, past_key_values=checked_cache,
                        max_new_tokens=remaining, do_sample=False, pad_token_id=tokenizer.eos_token_id,
                    )[0, full_ids.shape[1]:]
        return model.generate(
            **inputs, past_key_values=deepcopy(cache), max_new_tokens=self.max_new_tokens,
            do_sample=False, pad_token_id=tokenizer.eos_token_id,
        )[0, full_ids.shape[1]:]

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
