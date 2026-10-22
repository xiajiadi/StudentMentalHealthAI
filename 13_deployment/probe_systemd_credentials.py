"""Report a safe result from a real systemd LoadCredentialEncrypted unit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    try:
        repo = args.repo_root.resolve(strict=True)
        sys.path.insert(0, str(repo / "11_database"))
        from database_layer import LinuxSystemdCredentialKeyProvider

        provider = LinuxSystemdCredentialKeyProvider.from_env()
        print(
            json.dumps(
                {
                    "systemd_credential_injection": "PASS",
                    "key_provider": "LinuxSystemdCredentialKeyProvider",
                    "active_version_label": provider.active_version,
                    "effective_uid": __import__("os").geteuid(),
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - never render a path or credential error detail.
        print(
            json.dumps(
                {
                    "systemd_credential_injection": "BLOCKED",
                    "error_type": type(exc).__name__,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
