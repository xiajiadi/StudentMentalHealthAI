from __future__ import annotations

import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MODULE_ROOT.parent
sys.path.insert(0, str(MODULE_ROOT / "src"))


def declared_metadata(category: str) -> dict[str, object]:
    return {
        "organization": "合成测试组织",
        "author": None,
        "published_year": 2025,
        "source_type": "government" if category == "policy" else "academic" if category == "theory" else "practice_guidance",
        "source_url": "https://example.invalid/fixture",
        "language": "zh-CN",
        "population_scope": ["synthetic_students"],
        "category": category,
        "rights_status": "verified",
        "review_status": "approved",
        "role_scope": ["student", "teacher", "parent"],
        "risk_scope": ["normal", "attention"],
    }

