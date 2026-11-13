# Showrunner

Showrunner takes TV shows and movies to "finished": subtitles synced, re-split or translated, tracks
selected, MKV muxed, metadata, names, cover and chapters set. It is a desktop app (Python and PySide6)
with a companion command line, licensed GPL-3.0-or-later.

## Setup

Requires Python 3.12 or newer.

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

Tests run Qt headless; no display is needed.
