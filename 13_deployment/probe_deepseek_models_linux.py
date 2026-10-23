"""Check the encrypted DeepSeek credential against the non-generating Models API."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

EXPECTED_MODEL = "deepseek-flash"
CREDENTIAL_FILENAME = "deepseek-api-key"


def _provider_factory(credential_file: Path):
    import importlib

    source_path = _runtime_source_path(Path(__file__).resolve().parent)
    if source_path is None:
        raise ImportError("DeepSeek Runtime source is unavailable")
    sys.path.insert(0, str(source_path))

    module = importlib.import_module("llm_runtime.providers.deepseek")

    return module.DeepSeekProvider.from_credential_file(
        credential_file,
        timeout_seconds=20.0,
    )


def _runtime_source_path(script_dir: Path) -> Path | None:
    source_paths = (
        script_dir / "services" / "llm" / "release" / "src",
        script_dir / "release" / "06_llm-runtime" / "src",
        script_dir.parent / "06_llm-runtime" / "src",
    )
    return next(
        (path for path in source_paths if (path / "llm_runtime").is_dir()),
        None,
    )


def _safe_failure(exc: Exception) -> dict[str, object]:
    code = getattr(getattr(exc, "code", None), "value", None)
    if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code):
        return {"probe": "BLOCKED", "error_code": code, "generation_requests": 0}
    return {
        "probe": "BLOCKED",
        "error_type": type(exc).__name__,
        "generation_requests": 0,
    }


def probe(
    *,
    credential_directory: str | Path | None = None,
    provider_factory: Callable[[Path], Any] | None = None,
) -> dict[str, object]:
    directory = credential_directory or os.environ.get("CREDENTIALS_DIRECTORY")
    if not isinstance(directory, (str, Path)) or not str(directory):
        return {"probe": "BLOCKED", "error_code": "CREDENTIAL_DIRECTORY_UNAVAILABLE"}
    credential_root = Path(directory)
    if not credential_root.is_absolute():
        return {"probe": "BLOCKED", "error_code": "CREDENTIAL_DIRECTORY_INVALID"}

    provider = None
    result: dict[str, object]
    try:
        factory = provider_factory or _provider_factory
        provider = factory(credential_root / CREDENTIAL_FILENAME)
        models = provider.discover_models()
        model_ids = {
            item.get("provider_model_id")
            for item in models
            if isinstance(item, dict) and isinstance(item.get("provider_model_id"), str)
        }
        if EXPECTED_MODEL not in model_ids:
            result = {
                "probe": "BLOCKED",
                "error_code": "EXPECTED_MODEL_UNAVAILABLE",
                "models_count": len(model_ids),
                "generation_requests": 0,
            }
        else:
            result = {
                "probe": "PASS",
                "api_status": "reachable",
                "expected_model_available": True,
                "models_count": len(model_ids),
                "generation_requests": 0,
            }
    except Exception as exc:  # noqa: BLE001 - provider details and credentials stay private
        result = _safe_failure(exc)
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - cleanup error text may contain private details
                result = {
                    "probe": "BLOCKED",
                    "error_code": "PROVIDER_CLOSE_FAILED",
                    "generation_requests": 0,
                }
    return result


def main() -> int:
    result = probe()
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("probe") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
