"""The help tips: one entry per topic, each with a title, an explanation and a worked example in the string catalog.
QML names a topic and draws what comes back; a new tip is a new name here and three strings."""

from __future__ import annotations

from showrunner.ui.i18n.catalog import tr

HELP_TOPICS: tuple[str, ...] = (
    "rules",
    "first_kept",
    "exclude",
    "replace_values",
    "separators",
    "discard",
    "names",
    "language",
    "keep",
    "queue",
    # One per row of the Subtitles place, named by the row's key.
    "subtitles_wanted",
    "subtitles_translate",
    "subtitles_reference",
    "subtitles_names",
    "subtitles_cleanup",
    "subtitles_sync",
    "subtitles_lines",
    "subtitles_model",
    "subtitles_approval",
    "subtitles_output",
)


def help_topic(topic: str) -> dict[str, str]:
    """The text of one tip. `name` is what a screen reader says for the "?" button."""
    if topic not in HELP_TOPICS:
        raise KeyError(f"No help topic {topic!r}")
    title = tr(f"help.{topic}.title")
    return {
        "title": title,
        "explanation": tr(f"help.{topic}.explanation"),
        "example_label": tr("help.example"),
        "example": tr(f"help.{topic}.example"),
        "name": tr("help.label", topic=title),
    }
