"""Rank text from one approved feedback revision using a local embedding model."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MAX_BYTES = 12_000
MAX_PASSAGES = 16
_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


def _disable_network() -> None:
    import ctypes
    import errno

    lib = ctypes.CDLL("libseccomp.so.2")
    lib.seccomp_init.argtypes = (ctypes.c_uint32,)
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = (ctypes.c_char_p,)
    lib.seccomp_rule_add.argtypes = (ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint)
    lib.seccomp_load.argtypes = (ctypes.c_void_p,)
    lib.seccomp_release.argtypes = (ctypes.c_void_p,)
    lib.seccomp_release.restype = None
    allow = 0x7FFF0000  # SCMP_ACT_ALLOW
    deny = 0x00050000 | errno.EPERM  # SCMP_ACT_ERRNO(EPERM)
    context = lib.seccomp_init(allow)
    if not context:
        raise OSError("network isolation could not start")
    try:
        for name in (b"socket", b"socketpair", b"connect", b"io_uring_setup"):
            syscall = lib.seccomp_syscall_resolve_name(name)
            if syscall < 0 or lib.seccomp_rule_add(context, deny, syscall, 0) != 0:
                raise OSError("network isolation could not be configured")
        if lib.seccomp_load(context) != 0:
            raise OSError("network isolation could not be loaded")
    finally:
        lib.seccomp_release(context)


def similarities(question: str, passages: list[str], model: Path) -> list[float]:
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(model / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=256)
    tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
    tokens = tokenizer.encode_batch([_QUERY_PREFIX + question, *passages])
    inputs = {
        "input_ids": np.array([token.ids for token in tokens], dtype=np.int64),
        "attention_mask": np.array([token.attention_mask for token in tokens], dtype=np.int64),
        "token_type_ids": np.array([token.type_ids for token in tokens], dtype=np.int64),
    }
    ort.disable_telemetry_events()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(model / "model_uint8.onnx"), options, providers=["CPUExecutionProvider"]
    )
    feed = {item.name: inputs[item.name] for item in session.get_inputs()}
    hidden = session.run(["last_hidden_state"], feed)[0]
    embeddings = hidden[:, 0]
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    if not np.isfinite(embeddings).all() or (norms <= 0).any():
        raise ValueError("invalid embeddings")
    embeddings = embeddings / norms
    return (embeddings[1:] @ embeddings[0]).tolist()


def main() -> int:
    if not sys.platform.startswith("linux"):
        return 3
    import resource

    try:
        resource.setrlimit(resource.RLIMIT_CPU, (9, 9))
        resource.setrlimit(resource.RLIMIT_AS, (1_024 * 1024**2, 1_024 * 1024**2))
        _disable_network()
    except (OSError, ValueError):
        return 3
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    payload = sys.stdin.buffer.read(MAX_BYTES + 1)
    if not 1 <= len(payload) <= MAX_BYTES:
        return 2
    try:
        value = json.loads(payload)
        question, passages = value["question"], value["passages"]
        if (
            not isinstance(question, str)
            or not 1 <= len(question) <= 240
            or not isinstance(passages, list)
            or not 1 <= len(passages) <= MAX_PASSAGES
            or any(
                not isinstance(passage, str) or not 1 <= len(passage) <= 240
                for passage in passages
            )
        ):
            return 2
        values = similarities(question, passages, Path(sys.argv[1]))
    except Exception:
        return 3
    sys.stdout.write(json.dumps(values, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
