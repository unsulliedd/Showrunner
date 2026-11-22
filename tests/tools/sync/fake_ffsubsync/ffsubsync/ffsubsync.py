"""Stands in for ffsubsync's module in the worker's child process, put first on its path: it answers what the test
asks for through environment variables, and writes the arguments it was given to a file."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

logger = logging.getLogger("fake.ffsubsync")


class _Parser:
    def parse_args(self, argv: list[str]) -> argparse.Namespace:
        return argparse.Namespace(argv=argv)


def make_parser() -> _Parser:
    return _Parser()


def run(args: argparse.Namespace, progress_handler=None) -> dict[str, object]:
    argv: list[str] = args.argv
    Path(os.environ["FAKE_ARGS"]).write_text("\n".join(argv), encoding="utf-8")
    mode = os.environ.get("FAKE_MODE", "ok")
    if mode == "slow":
        time.sleep(60)
    if mode == "refuse":
        logger.error("refused: %s", "no speech in the reference")
        return {"retval": 1, "offset_seconds": None, "framerate_scale_factor": None}
    for fraction in (0.25, 0.5, 1.0):
        progress_handler(SimpleNamespace(processed_seconds=fraction * 100, total_seconds=100.0))
    logger.info("score: %.3f", float(os.environ.get("FAKE_SCORE", "1000")))
    shutil.copyfile(argv[argv.index("-i") + 1], argv[argv.index("-o") + 1])
    return {
        "retval": 0,
        "offset_seconds": float(os.environ.get("FAKE_OFFSET", "-2.0")),
        "framerate_scale_factor": float(os.environ.get("FAKE_SCALE", "1.0")),
        "sync_was_successful": mode != "unsure",
    }
