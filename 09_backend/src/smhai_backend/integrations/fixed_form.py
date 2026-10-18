"""Strict WHO-5 English fixed-form documents and session behavior.

This adapter presents the published items in source order. It does not estimate
traits, compute a score, classify risk, or create a psychological interpretation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, model_validator
from typing_extensions import Annotated

from smhai_backend.domains.models import AssessmentRecord
from smhai_backend.integrations.cat import CatStart

WHO5_INSTRUMENT_ID = "WHO5_2024_EN"
WHO5_VERSION = "2024.1"
WHO5_ITEM_BANK_ID = "WHO5_EN_2024"
WHO5_ITEM_BANK_VERSION = "2024.1"
WHO5_CONFIG_VERSION = "WHO5_2024_EN_2024.1"
WHO5_OPTIONS = (
    "All of the time",
    "Most of the time",
    "More than half of the time",
    "Less than half of the time",
    "Some of the time",
    "At no time",
)
WHO5_STEMS = (
    "I have felt cheerful and in good spirits",
    "I have felt calm and relaxed",
    "I have felt active and vigorous",
    "I woke up feeling fresh and rested",
    "My daily life has been filled with things that interest me",
)
WHO5_SOURCE = (
    "WHO. The World Health Organization-Five Well-Being Index (WHO-5), 2024. "
    "CC BY-NC-SA 3.0 IGO."
)


class _StrictDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Metadata(_StrictDocument):
    synthetic: Literal[True]
    intended_use: Literal["engineering_test_only"]
    psychological_interpretation_allowed: Literal[False]
    instrument_version: Literal["2024.1"]
    notice: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    psychometric_status: Literal["PENDING_PSYCHOMETRIC_CONFIRMATION"] | None = None


class _Item(_StrictDocument):
    item_id: Annotated[str, StringConstraints(pattern=r"^ITEM_WHO5_2024_[1-5]$")]
    dimension: Literal["wellbeing"]
    stem: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    response_type: Literal["likert"]
    response_options: Annotated[list[str], Field(min_length=6, max_length=6)]
    scoring: dict[str, StrictInt]
    model: Literal["FIXED_FORM"]
    source: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    status: Literal["published"]

    @model_validator(mode="after")
    def validate_original_choices(self):
        if tuple(self.response_options) != WHO5_OPTIONS:
            raise ValueError("WHO-5 options must retain the original English order")
        if self.scoring != {option: 5 - index for index, option in enumerate(WHO5_OPTIONS)}:
            raise ValueError("WHO-5 options must retain the original raw scoring")
        if self.source != WHO5_SOURCE:
            raise ValueError("WHO-5 source attribution must be retained")
        return self


class _BankDocument(_StrictDocument):
    item_bank_id: Literal["WHO5_EN_2024"]
    version: Literal["2024.1"]
    instrument_id: Literal["WHO5_2024_EN"]
    target_population: Literal["English-language respondents"]
    measurement_model: Literal["FIXED_FORM"]
    dimensions: Annotated[list[Literal["wellbeing"]], Field(min_length=1, max_length=1)]
    items: Annotated[list[_Item], Field(min_length=5, max_length=5)]
    status: Literal["published"]
    instructions: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    metadata: _Metadata

    @model_validator(mode="after")
    def validate_original_form(self):
        if self.metadata.instrument_version != WHO5_VERSION:
            raise ValueError("WHO-5 instrument version must be retained")
        if tuple(item.stem for item in self.items) != WHO5_STEMS:
            raise ValueError("WHO-5 English items must retain source order and wording")
        if tuple(item.item_id for item in self.items) != tuple(
            f"ITEM_WHO5_2024_{index}" for index in range(1, 6)
        ):
            raise ValueError("WHO-5 item IDs must retain source order")
        return self


class _ConfigDocument(_StrictDocument):
    config_version: Literal["WHO5_2024_EN_2024.1"]
    model: Literal["FIXED_FORM"]
    selection_method: Literal["SEQUENTIAL"]
    min_items: Annotated[StrictInt, Field(ge=5, le=5)]
    max_items: Annotated[StrictInt, Field(ge=5, le=5)]
    scoring_rule: Literal["SUM"]


def validate_who5_documents(
    bank_document: dict[str, Any], config_document: dict[str, Any] | None
) -> dict[str, Any]:
    """Validate a saved fixed-form asset and return canonical JSON documents."""

    bank = _BankDocument.model_validate(bank_document)
    config = _ConfigDocument.model_validate(config_document) if config_document is not None else None
    if config is not None and (config.min_items != len(bank.items) or config.max_items != len(bank.items)):
        raise ValueError("WHO-5 plan item counts must match the fixed form")
    return {
        "engineering_only": True,
        "psychological_interpretation_allowed": False,
        "bank_document": bank.model_dump(mode="json", exclude_none=True),
        "config_document": config.model_dump(mode="json") if config is not None else None,
        "item_count": len(bank.items),
        "dimension_count": 1,
    }


def is_who5_fixed_form(record: AssessmentRecord) -> bool:
    bank = record.saved_bank_document
    return (
        record.cat_binding_mode == "SAVED_VERSION"
        and isinstance(bank, dict)
        and bank.get("measurement_model") == "FIXED_FORM"
    )


def start_who5_session(record: AssessmentRecord, saved_binding: dict[str, str]) -> CatStart:
    bank = record.saved_bank_document
    config = record.saved_config_document
    if not isinstance(bank, dict) or not isinstance(config, dict):
        raise ValueError("WHO-5 saved assets are unavailable")
    validated = validate_who5_documents(bank, config)
    bank = validated["bank_document"]
    config = validated["config_document"]
    items = bank["items"]
    responses = record.responses
    answered_count = len(responses)
    if answered_count > len(items):
        raise ValueError("WHO-5 response history exceeds the fixed form")
    for index, item in enumerate(items):
        item_id = item["item_id"]
        if index < answered_count:
            if item_id not in responses or responses[item_id] not in WHO5_OPTIONS:
                raise ValueError("WHO-5 response history does not match source order")
        elif item_id in responses:
            raise ValueError("WHO-5 response history is not a sequential prefix")

    current_item = None
    if answered_count < len(items):
        selected = items[answered_count]
        current_item = {
            "item_id": selected["item_id"],
            "prompt": selected["stem"],
            "response_type": selected["response_type"],
            "options": [{"value": option, "label": option} for option in WHO5_OPTIONS],
            "instructions": bank["instructions"],
            "source_attribution": bank["metadata"]["notice"],
        }
    started_at = record.assessment.get("timestamps", {}).get("started_at")
    if not isinstance(started_at, str) or not started_at:
        raise ValueError("WHO-5 assessment start time is unavailable")
    instrument = record.assessment.get("instrument")
    if not isinstance(instrument, dict) or instrument.get("instrument_id") != WHO5_INSTRUMENT_ID:
        raise ValueError("WHO-5 assessment identity changed")
    if instrument.get("version") != WHO5_VERSION:
        raise ValueError("WHO-5 assessment version changed")
    if record.cat_item_bank_version != bank["version"] or record.cat_config_version != config["config_version"]:
        raise ValueError("WHO-5 saved version binding changed")
    if set(saved_binding) != {"binding_ref", "activation_ref", "plan_version_ref", "bank_version_ref"}:
        raise ValueError("WHO-5 saved task binding is unavailable")
    return CatStart(
        assessment_id=record.assessment_id,
        subject_id=record.subject_id,
        instrument_id=WHO5_INSTRUMENT_ID,
        instrument_version=WHO5_VERSION,
        started_at=started_at,
        current_item=current_item,
        current_index=answered_count,
        answered_count=answered_count,
        administered_count=answered_count,
        can_complete=answered_count == len(items),
        max_items=len(items),
        item_bank_version=bank["version"],
        config_version=config["config_version"],
        provider_version="who5-fixed-form-1",
        cat_binding_mode="SAVED_VERSION",
        saved_binding=saved_binding,
    )


def advance_who5_session(
    session: CatStart, *, item_id: str, response: Any
) -> CatStart:
    current = session.current_item
    if current is None or current.get("item_id") != item_id:
        raise ValueError("WHO-5 response item does not match the current item")
    if type(response) is not str or response not in WHO5_OPTIONS:
        raise ValueError("WHO-5 response is not a published option")
    next_index = session.current_index + 1
    bank_items = WHO5_STEMS
    next_item = None
    if next_index < len(bank_items):
        next_item = {
            "item_id": f"ITEM_WHO5_2024_{next_index + 1}",
            "prompt": bank_items[next_index],
            "response_type": "likert",
            "options": [{"value": option, "label": option} for option in WHO5_OPTIONS],
            "instructions": current.get("instructions"),
            "source_attribution": current.get("source_attribution"),
        }
    return CatStart(
        assessment_id=session.assessment_id,
        subject_id=session.subject_id,
        instrument_id=session.instrument_id,
        instrument_version=session.instrument_version,
        started_at=session.started_at,
        current_item=next_item,
        current_index=next_index,
        answered_count=next_index,
        administered_count=next_index,
        can_complete=next_index == len(bank_items),
        max_items=len(bank_items),
        item_bank_version=session.item_bank_version,
        config_version=session.config_version,
        provider_version="who5-fixed-form-1",
        cat_binding_mode=session.cat_binding_mode,
        saved_binding=session.saved_binding,
    )


def complete_who5_assessment(record: AssessmentRecord, session: CatStart) -> dict[str, Any]:
    if not session.can_complete or len(record.responses) != 5:
        raise ValueError("WHO-5 requires all five original items")
    return {
        "schema_version": "assessment.v1",
        "assessment_id": record.assessment_id,
        "subject_id": record.subject_id,
        "instrument": {"instrument_id": WHO5_INSTRUMENT_ID, "version": WHO5_VERSION},
        "population_scope": record.saved_bank_document["target_population"],
        "status": "completed",
        "dimensions": {
            "wellbeing": {
                "theta": None,
                "se": None,
                "score": None,
                "band": "unknown",
                "interpretation_status": "not_scored",
                "items_answered": 5,
            }
        },
        "risk": {
            "level": "not_assessed",
            "need_human_review": False,
            "reason_codes": ["FIXED_FORM_NOT_ASSESSED"],
            "ruleset_id": "RULESET_FIXED_FORM_NOT_ASSESSED",
        },
        "response_summary": {"items_answered": 5, "duration_seconds": None},
        "provenance": {
            "source_adapter": "who5_fixed_form_backend",
            "adapter_version": "1.0.0",
            "cat_engine_version": "not_applicable",
            "item_bank_version": record.saved_bank_document["version"],
        },
        "timestamps": {
            "started_at": session.started_at,
            "completed_at": datetime.now(UTC).isoformat(),
        },
    }
