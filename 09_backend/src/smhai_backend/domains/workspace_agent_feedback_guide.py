"""Private extractive reading aid for one school's published feedback revision."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from smhai_backend.core.errors import ErrorCode, error

from .workspace_agent_feedback_worker import MAX_PASSAGES

MODEL = "bge-small-zh-v1.5-uint8"
_NEXT_STEPS = "\n\n【老师建议的下一步】\n"
_MIN_SIMILARITY = 0.57
_UNAVAILABLE = "private feedback guide is unavailable"


class FeedbackGuideQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    content_revision: int = Field(ge=1, le=2_147_483_647)
    question: str = Field(min_length=2, max_length=240)


def feedback_passages(body: str) -> list[tuple[str, str]]:
    feedback, _marker, steps = body.partition(_NEXT_STEPS)
    passages = []
    for group, source in (("next_steps", steps), ("feedback", feedback)):
        for part in re.split(r"(?<=[。！？!?])\s*|\n+", source):
            sentence = part.strip()
            if 6 <= len(sentence) <= 240 and all(c.isprintable() for c in sentence):
                passages.append((group, sentence))
    return list(dict.fromkeys(passages))[:MAX_PASSAGES]


def _scores(question: str, passages: list[str]) -> list[float]:
    directory = os.environ.get("PSYNOVA_WORKSPACE_FEEDBACK_DIRECTORY")
    if not directory:
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail=_UNAVAILABLE)
    root = Path(directory)
    executable = root / "venv" / "bin" / "python"
    model = root / "model"
    worker = Path(__file__).with_name("workspace_agent_feedback_worker.py")
    payload = json.dumps({"question": question, "passages": passages}, ensure_ascii=False).encode()
    try:
        result = subprocess.run(
            [str(executable), "-I", str(worker), str(model)],
            input=payload,
            capture_output=True,
            close_fds=True,
            timeout=12,
            check=False,
            env={"LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.TimeoutExpired):
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail=_UNAVAILABLE) from None
    if result.returncode != 0 or not 1 <= len(result.stdout) <= 1024:
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail=_UNAVAILABLE)
    try:
        scores = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        scores = None
    if (
        not isinstance(scores, list)
        or len(scores) != len(passages)
        or any(type(score) not in (float, int) or not math.isfinite(score) for score in scores)
    ):
        raise error(ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail=_UNAVAILABLE)
    return scores


def find_feedback_passages(question: str, body: str) -> list[dict[str, str]]:
    passages = feedback_passages(body)
    if not passages:
        return []
    scores = _scores(question, [sentence for _, sentence in passages])
    highest = max(scores)
    relevant = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
    return [
        {"source": passages[index][0], "text": passages[index][1]}
        for index in relevant[:2]
        if scores[index] >= max(_MIN_SIMILARITY, highest - 0.05)
    ]
