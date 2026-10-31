"""python3 -m cli_anything.photoshop → the same CLI as the entry point."""
from __future__ import annotations

import sys

from cli_anything.photoshop.photoshop_cli import cli

if __name__ == "__main__":
    sys.exit(cli(prog_name="python3 -m cli_anything.photoshop"))
