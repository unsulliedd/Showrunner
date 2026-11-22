"""Importing this module registers the options of every stage, so a profile keeps all its sections.

`profile_to_json` and `profile_from_json` only know the stages registered at the time, and a stage registers
when its options module is imported. The app and the command line import this module at start; a new stage's
options module is added here and nowhere else.
"""

from showrunner.core.naming import options as naming
from showrunner.stages.metadata import options as metadata
from showrunner.stages.mux import options as mux
from showrunner.stages.scan import options as scan
from showrunner.stages.subtitles import options as subtitles
from showrunner.stages.tracks import options as tracks

OPTIONS_MODULES = (naming, scan, tracks, subtitles, mux, metadata)
