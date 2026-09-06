"""Explicitly create a development encryption-key file outside the repository."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database_layer.crypto import generate_key_file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--path",
        type=Path,
        default=Path(r"D:\Dev\secrets\studentmentalhealthai\database-keys.json"),
    )
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    resolved = args.path.expanduser().resolve()
    if resolved == repository_root or repository_root in resolved.parents:
        raise SystemExit("The key path must be outside the repository.")
    if resolved.exists():
        raise SystemExit("The key file already exists; refusing to overwrite it.")
    generate_key_file(resolved, active_version=args.version)
    print(f"Development key created outside the repository: {resolved}")


if __name__ == "__main__":
    main()
