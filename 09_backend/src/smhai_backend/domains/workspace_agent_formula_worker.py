"""Read one isolated formula image from stdin using the pinned local ONNX model."""

from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path

MAX_BYTES = 768 * 1024
MAX_SIDE = 640
MAX_TOKENS = 64


def _read_pixels(payload: bytes):
    import numpy as np
    from PIL import Image

    with Image.open(io.BytesIO(payload), formats=("PNG",)) as source:
        if max(source.size) > MAX_SIDE or source.n_frames != 1:
            raise ValueError("unsupported image dimensions")
        rgba = source.convert("RGBA")
    image = Image.new("RGB", rgba.size, "white")
    image.paste(rgba, mask=rgba.getchannel("A"))
    ink = (np.asarray(image).min(axis=2) < 200).mean()
    if not 0.001 <= ink <= 0.55:
        raise ValueError("no distinct formula")
    resized = np.asarray(image.resize((384, 384), Image.Resampling.BICUBIC), dtype=np.float32)
    return ((resized / 255 - 0.5) * 2).transpose(2, 0, 1)[None, ...].copy()


def _checked_formula(text: str) -> str:
    if not text or len(text) > 700 or "\ufffd" in text or not all(c.isprintable() for c in text):
        raise ValueError("unreadable formula")
    if not re.search(r"[0-9+\-=×÷√∫∑^_\\]", text):
        raise ValueError("no distinct formula")
    if re.search(r"(?:^|[=+−\-({])\s*(?:\\\s+)?(?:[×÷·]|\\(?:cdot|times|div)\b)", text):
        raise ValueError("operator without a left operand")
    depth = 0
    for brace in re.findall(r"(?<!\\)[{}]", text):
        depth += 1 if brace == "{" else -1
        if depth < 0:
            raise ValueError("incomplete formula")
    if depth:
        raise ValueError("incomplete formula")
    return text


def recognize(payload: bytes, model: Path) -> str:
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer

    pixels = _read_pixels(payload)
    ort.disable_telemetry_events()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    encoder = ort.InferenceSession(
        str(model / "encoder_model.onnx"), options, providers=["CPUExecutionProvider"]
    )
    decoder = ort.InferenceSession(
        str(model / "decoder_model.onnx"), options, providers=["CPUExecutionProvider"]
    )
    hidden = encoder.run(["last_hidden_state"], {"pixel_values": pixels})[0]
    tokens = [1]
    for _ in range(MAX_TOKENS):
        output = decoder.run(["logits"], {
            "input_ids": np.array([tokens], dtype=np.int64),
            "encoder_hidden_states": hidden,
        })[0]
        next_token = int(output[0, -1].argmax())
        if next_token == 2:
            tokenizer = Tokenizer.from_file(str(model / "tokenizer.json"))
            return _checked_formula(tokenizer.decode(tokens, skip_special_tokens=True).strip())
        if next_token < 5:
            raise ValueError("unreadable formula token")
        tokens.append(next_token)
    raise ValueError("formula length limit reached")


def main() -> int:
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
        resource.setrlimit(resource.RLIMIT_AS, (1_536 * 1024**2, 1_536 * 1024**2))
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    payload = sys.stdin.buffer.read(MAX_BYTES + 1)
    if not 1 <= len(payload) <= MAX_BYTES:
        return 2
    try:
        formula = recognize(payload, Path(sys.argv[1]))
    except (ImportError, FileNotFoundError):
        return 3
    except Exception:
        return 2
    sys.stdout.buffer.write(formula.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
