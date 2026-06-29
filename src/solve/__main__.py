"""Allow ``python -m solve`` to dispatch to the CLI."""

from __future__ import annotations

from solve.cli import main


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
