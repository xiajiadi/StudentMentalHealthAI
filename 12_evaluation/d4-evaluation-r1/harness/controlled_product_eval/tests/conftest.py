from __future__ import annotations

import sys
from pathlib import Path

EVALUATION_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
for candidate in (EVALUATION_ROOT, REPOSITORY_ROOT / "05_rag-engine" / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
