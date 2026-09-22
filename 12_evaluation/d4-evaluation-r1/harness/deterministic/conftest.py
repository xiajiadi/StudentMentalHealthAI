from __future__ import annotations

import sys
from pathlib import Path

EVALUATION_ROOT = Path(__file__).resolve().parents[2]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))
