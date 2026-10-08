"""Fail closed until per-record M0 demo reset markers are available."""


def main() -> int:
    print(
        "M0 database reset is blocked: no durable per-record M0 demo marker "
        "exists; no database connection was opened."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
