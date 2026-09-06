"""Provider-neutral item representation and response scoring."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from .errors import ItemBankValidationError, ResponseValidationError

ResponseValue = str | int | float | bool


@dataclass(frozen=True)
class Item:
    """One immutable item and its published model parameters."""

    item_id: str
    dimension: str
    stem: str
    response_type: str
    response_options: tuple[str, ...]
    scoring: Mapping[str, int]
    model: str
    parameters: Mapping[str, Any]
    source: str
    status: str

    @classmethod
    def from_dict(cls, source: Mapping[str, Any]) -> "Item":
        required = {
            "item_id",
            "dimension",
            "stem",
            "response_type",
            "response_options",
            "scoring",
            "model",
            "parameters",
            "source",
            "status",
        }
        missing = sorted(required.difference(source))
        if missing:
            raise ItemBankValidationError(f"item missing fields: {', '.join(missing)}")
        options = source["response_options"]
        scoring = source["scoring"]
        if not isinstance(options, (list, tuple)):
            raise ItemBankValidationError("response_options must be a list")
        if not isinstance(scoring, Mapping):
            raise ItemBankValidationError("scoring must be an object")
        try:
            scoring_values = {str(key): int(value) for key, value in scoring.items()}
        except (TypeError, ValueError) as exc:
            raise ItemBankValidationError("scoring values must be integer category indexes") from exc
        item = cls(
            item_id=str(source["item_id"]),
            dimension=str(source["dimension"]),
            stem=str(source["stem"]),
            response_type=str(source["response_type"]),
            response_options=tuple(str(value) for value in options),
            scoring=scoring_values,
            model=str(source["model"]),
            parameters=dict(source["parameters"]) if isinstance(source["parameters"], Mapping) else {},
            source=str(source["source"]),
            status=str(source["status"]),
        )
        item.validate()
        return item

    def validate(self) -> None:
        """Validate response categories and the model parameters needed online."""

        if not self.item_id or not self.item_id.startswith("ITEM_"):
            raise ItemBankValidationError(f"invalid item_id: {self.item_id!r}")
        if not self.dimension or not self.stem or not self.source:
            raise ItemBankValidationError(f"item {self.item_id} has an empty required text field")
        if len(self.response_options) < 2 or len(set(self.response_options)) != len(self.response_options):
            raise ItemBankValidationError(f"item {self.item_id} needs unique response options")
        expected = set(self.response_options)
        if set(self.scoring) != expected:
            raise ItemBankValidationError(f"item {self.item_id} scoring keys must match response_options")
        scores = list(self.scoring.values())
        if sorted(scores) != list(range(len(self.response_options))):
            raise ItemBankValidationError(f"item {self.item_id} scoring must be contiguous category indexes")
        if self.model not in {"GRM", "GPCM"}:
            raise ItemBankValidationError(f"item {self.item_id} has unsupported model {self.model!r}")
        if not self.parameters:
            raise ItemBankValidationError(f"item {self.item_id} is missing parameters")
        a = self.parameters.get("a")
        thresholds = self.parameters.get("thresholds")
        if not isinstance(a, (int, float)) or isinstance(a, bool) or not math.isfinite(float(a)) or float(a) <= 0:
            raise ItemBankValidationError(f"item {self.item_id} requires a positive finite a parameter")
        if not isinstance(thresholds, (list, tuple)) or len(thresholds) != len(self.response_options) - 1:
            raise ItemBankValidationError(
                f"item {self.item_id} requires one fewer threshold than response categories"
            )
        try:
            threshold_values = [float(value) for value in thresholds]
        except (TypeError, ValueError) as exc:
            raise ItemBankValidationError(f"item {self.item_id} thresholds must be numbers") from exc
        if any(not math.isfinite(value) for value in threshold_values):
            raise ItemBankValidationError(f"item {self.item_id} thresholds must be finite")
        if threshold_values != sorted(threshold_values) or len(set(threshold_values)) != len(threshold_values):
            raise ItemBankValidationError(f"item {self.item_id} thresholds must be strictly increasing")

    def score_response(self, response: ResponseValue) -> int:
        """Convert a public category label or index to the provider category index."""

        if isinstance(response, bool):
            raise ResponseValidationError(f"boolean response is invalid for item {self.item_id}")
        if isinstance(response, (int, float)) and not isinstance(response, bool):
            if isinstance(response, float) and (not math.isfinite(response) or response != int(response)):
                raise ResponseValidationError(f"response index is invalid for item {self.item_id}")
            score = int(response)
            if score in range(len(self.response_options)):
                return score
            raise ResponseValidationError(f"response index is invalid for item {self.item_id}")
        if isinstance(response, str) and response in self.scoring:
            return self.scoring[response]
        raise ResponseValidationError(f"response is not a published option for item {self.item_id}")

    def option_for_score(self, score: int) -> str:
        """Convert a provider category index back to the published option label."""

        for option, option_score in self.scoring.items():
            if option_score == score:
                return option
        raise ResponseValidationError(f"provider returned invalid category {score} for item {self.item_id}")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible item object for diagnostics and fixtures."""

        return {
            "item_id": self.item_id,
            "dimension": self.dimension,
            "stem": self.stem,
            "response_type": self.response_type,
            "response_options": list(self.response_options),
            "scoring": dict(self.scoring),
            "model": self.model,
            "parameters": dict(self.parameters),
            "source": self.source,
            "status": self.status,
        }
