"""Archived native-messaging bridge that deliberately performs no handoff."""

import sys


def main() -> int:
    print("The legacy Barq browser bridge is retired.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
