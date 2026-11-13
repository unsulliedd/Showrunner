"""Library scan: videos and the subtitle files beside them, recognized and paired."""

from showrunner.stages.scan.manual import attach, detach, move_subtitle
from showrunner.stages.scan.options import ScanOptions
from showrunner.stages.scan.probing import ProbeBatch, ProbeFailure, probe_items
from showrunner.stages.scan.scanner import Alternatives, ScanResult, scan
from showrunner.stages.scan.subtitles import read_subtitle

__all__ = [
    "Alternatives",
    "ProbeBatch",
    "ProbeFailure",
    "ScanOptions",
    "ScanResult",
    "attach",
    "detach",
    "move_subtitle",
    "probe_items",
    "read_subtitle",
    "scan",
]
