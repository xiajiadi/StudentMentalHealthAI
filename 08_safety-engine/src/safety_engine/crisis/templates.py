"""Versioned, non-clinical crisis-route templates."""

from __future__ import annotations

import json
from pathlib import Path

from safety_engine.domain import (
    ActorRole,
    CrisisTemplate,
    ErrorCode,
    SafetyError,
)


class CrisisTemplateRepository:
    def __init__(self, template_dir: str | Path) -> None:
        self.template_dir = Path(template_dir)
        self._templates: dict[tuple[str, ActorRole], CrisisTemplate] = {}
        self._load()

    def _load(self) -> None:
        if not self.template_dir.exists():
            raise SafetyError(
                ErrorCode.CRISIS_TEMPLATE_UNAVAILABLE,
                "crisis template directory is missing",
                details={"template_dir": str(self.template_dir)},
            )
        for path in sorted(self.template_dir.glob("*.json")):
            try:
                template = CrisisTemplate.model_validate(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except Exception as exc:
                raise SafetyError(
                    ErrorCode.CRISIS_TEMPLATE_UNAVAILABLE,
                    "crisis template could not be loaded",
                    details={"template": path.name},
                ) from exc
            self._templates[(template.language, template.target_role)] = template

    def get(self, *, language: str = "zh-CN", target_role: ActorRole) -> CrisisTemplate:
        template = self._templates.get((language, target_role))
        if template is None:
            template = self._templates.get(("en-US", target_role))
        if template is None:
            template = self._templates.get(("en-US", ActorRole.STUDENT))
        if template is None:
            raise SafetyError(
                ErrorCode.CRISIS_TEMPLATE_UNAVAILABLE,
                "no crisis template is available for the requested role",
                details={"target_role": target_role.value},
            )
        return template

    def render(self, *, language: str, target_role: ActorRole) -> str:
        return self.get(language=language, target_role=target_role).content
