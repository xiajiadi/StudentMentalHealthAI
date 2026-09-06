"""Export the actual Backend app schema as a module-local provisional API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from smhai_backend.app_factory import create_app


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export the source-generated Backend OpenAPI document"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "reports" / "backend_round1_openapi.json",
    )
    args = parser.parse_args()
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
