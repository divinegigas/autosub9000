"""Entry point: GUI when started without arguments (or with --gui / a file path
from the desktop launcher), CLI otherwise."""

from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]
    cli_flags = [a for a in argv if a.startswith("-") and a != "--gui"]
    if cli_flags:
        from .cli import main as cli_main
        return cli_main(argv)
    from .gui.app import run_gui
    files = [a for a in argv if not a.startswith("-")]
    return run_gui(files)


if __name__ == "__main__":
    sys.exit(main())
