import argparse
from typing import Sequence

from . import app


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mikroclear", description="Run the Mikro-Clear service.")
    try:
        parser.parse_args([] if argv is None else argv)
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        raise
    return app.main()
