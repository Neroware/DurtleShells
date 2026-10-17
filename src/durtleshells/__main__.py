"""Entry point: ``durtleshells``."""

from __future__ import annotations

import sys


def main() -> int:
    from .config import Config
    from .ui.app import DurtleApp

    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print("usage: durtleshells\n\nA Vim-style terminal WaniKani client. Press ? inside for help.")
        return 0
    if len(sys.argv) > 1 and sys.argv[1] in ("-V", "--version"):
        from . import __version__

        print(f"durtleshells {__version__}")
        return 0
    config = Config.load()
    app = DurtleApp(config, token=config.resolve_token())
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
