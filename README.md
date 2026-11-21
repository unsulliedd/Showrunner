# Showrunner

Showrunner takes TV shows and movies to "finished": subtitles synced, re-split or translated, tracks
selected, MKV muxed, metadata, names, cover and chapters set. It is a desktop app (Python and PySide6)
with a companion command line, licensed GPL-3.0-or-later.

## Setup

Requires Python 3.12 or newer.

Showrunner reads tracks with [MKVToolNix](https://mkvtoolnix.download/) and
[FFmpeg](https://ffmpeg.org/). Both are optional and found automatically when installed; Tools >
Dependencies shows what was found and can download what is missing from its official source.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; on Linux and macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
showrunner            # opens the main window (same as: python -m showrunner)
showrunner-cli --version
```

## Tests and lint

```bash
pytest
ruff check
ruff format --check
```

Tests run Qt headless; no display is needed. `pytest` spreads the tests over worker processes, one per
CPU core and at most eight ([pytest-xdist](https://pytest-xdist.readthedocs.io/)); each test gets its
own data folder, so they do not meet. Named tests run in one process, and `-n 0` runs any selection there:

```bash
pytest tests/ui/quick/test_remove.py::test_the_library_menu_closes_after_close_folder_empties_the_list
pytest -n 0 tests/ui/quick/test_remove.py
```
