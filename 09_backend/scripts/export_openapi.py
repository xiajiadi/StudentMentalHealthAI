"""Export the actual Backend app schema as a module-local provisional API."""

from __future__ import annotations

import json
from pathlib import Path

from smhai_backend.app_factory import create_app


def main() -> None:
    output_path = Path(__file__).resolve().parents[1] / "reports" / "backend_round1_openapi.json"
    output_path.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_path)


if __name__ == "__main__":
    main()
