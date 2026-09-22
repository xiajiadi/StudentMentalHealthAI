from __future__ import annotations

import sys
from pathlib import Path


D4_ROOT = Path(__file__).resolve().parents[3]
if str(D4_ROOT) not in sys.path:
    sys.path.insert(0, str(D4_ROOT))
