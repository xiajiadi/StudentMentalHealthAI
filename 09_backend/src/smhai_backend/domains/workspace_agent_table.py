"""Allowlisted numeric summaries from the user's local spreadsheet preview."""

from __future__ import annotations

from math import isclose

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class NumericColumn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    column: int = Field(ge=1, le=40)
    count: int = Field(ge=1, le=2000)
    min: FiniteFloat = Field(ge=-1e9, le=1e9)
    max: FiniteFloat = Field(ge=-1e9, le=1e9)
    mean: FiniteFloat = Field(ge=-1e9, le=1e9)
    sum: FiniteFloat = Field(ge=-2e12, le=2e12)

    @model_validator(mode="after")
    def validate_statistics(self):
        if (
            not self.min <= self.max
            or not self.min - 1e-6 <= self.mean <= self.max + 1e-6
            or not isclose(self.mean, self.sum / self.count, rel_tol=1e-10, abs_tol=1e-9)
        ):
            raise ValueError("inconsistent numeric summary")
        return self


class WorkspaceTableSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    rows: int = Field(ge=1, le=2000)
    columns: list[NumericColumn] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_columns(self):
        if len({item.column for item in self.columns}) != len(self.columns):
            raise ValueError("duplicate column numbers")
        if any(item.count > self.rows for item in self.columns):
            raise ValueError("numeric count exceeds row count")
        return self
