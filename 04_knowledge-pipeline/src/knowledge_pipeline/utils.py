"""Small deterministic utilities shared by pipeline stages."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def stable_digest(*parts: object, length: int = 20) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:length]


def stable_id(prefix: str, *parts: object, length: int = 20) -> str:
    return f"{prefix}_{stable_digest(*parts, length=length)}"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_text(text: str) -> str:
    """Conservatively normalize parser whitespace without rewriting meaning."""

    # Keep the displayed/source excerpt faithful. Compatibility normalization is
    # reserved for the hash view below, so full-width punctuation and symbols do
    # not silently change in the contract text.
    value = text.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(char for char in value if char in "\n\t" or not unicodedata.category(char).startswith("C"))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(lines).strip()


def normalized_for_hash(text: str) -> str:
    value = unicodedata.normalize("NFKC", normalize_text(text))
    return re.sub(r"\s+", " ", value).strip()


def content_hash(text: str) -> str:
    return f"sha256:{sha256_bytes(normalized_for_hash(text).encode('utf-8'))}"


_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_WORD = re.compile(r"[A-Za-z0-9]+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def estimate_tokens(text: str) -> int:
    """Deterministic budget estimate used when no embedding tokenizer is loaded.

    It is deliberately used only for configured secondary splitting and quality
    gates. The canonical text remains unchanged and the tokenizer name is
    recorded in the manifest so a later benchmark can replace this baseline.
    """

    value = normalize_text(text)
    cjk = len(_CJK.findall(value))
    words = len(_WORD.findall(value))
    punctuation = len(_PUNCT.findall(value))
    return max(1, cjk + words + (punctuation // 4))


def first_non_empty(values: Iterable[str | None], default: str = "") -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return default
