#!/usr/bin/env python3
"""Entry point for the backup-aware install/status/uninstall tool."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orca_install.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
