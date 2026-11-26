"""Read the same general-education articles shown on the student's knowledge page."""

import json
from functools import cache
from importlib.resources import files
from typing import Literal

EducationTopic = Literal["emotions", "stress", "sleep", "support"]


@cache
def student_education_articles() -> dict[str, dict]:
    catalog = files("smhai_backend.domains").joinpath("student_education_articles.json")
    return {article["id"]: article for article in json.loads(catalog.read_text(encoding="utf-8"))}
