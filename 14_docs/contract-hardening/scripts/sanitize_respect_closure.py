"""Copy Respect JSON logs into committed evidence with secrets removed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def sanitize(key: str, value: Any) -> Any:
    lowered = key.lower()
    if lowered == "username":
        return "<synthetic-username>"
    if "password" in lowered:
        return "<redacted>"
    if "csrf" in lowered or "authorization" in lowered:
        return "<redacted>"
    if "cookie" in lowered or lowered == "set-cookie":
        if lowered == "set-cookie":
            return "smhai_dev_session=<redacted>; HttpOnly; Max-Age=1800; Path=/; SameSite=lax"
        return "<redacted>"
    if isinstance(value, dict):
        return {item_key: sanitize(item_key, item_value) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [sanitize(key, item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.source.read_text(encoding="utf-8"))
    args.target.write_text(
        json.dumps(sanitize("root", payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
