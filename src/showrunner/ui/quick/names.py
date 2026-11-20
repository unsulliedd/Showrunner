"""What the Names place and its Tokens panel draw, and the edits the builder rail makes to a template.

The rail is a view over the template text: it is parsed with the engine's `parse`, shown as its pieces, and every
edit writes a template string back (`write`), so the profile only ever holds text the engine reads. A template with
syntax problems is shown as text and not edited piece by piece, since its broken parts have no piece.

What a name becomes is rendered with the metadata stage's own context (`naming_context`); whether it is written, and
how many names a card changes, comes from the live plan, so the cards agree with the tab's count.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from showrunner.app.batches.batch import Media
from showrunner.app.jobs.blocked import StageBlock, template_problems
from showrunner.app.jobs.groups import TITLE_TEMPLATE, TRACK_TEMPLATES
from showrunner.app.jobs.preview import FileOutcome, FilePreview
from showrunner.app.jobs.stages import PlanState
from showrunner.app.profiles.profile import Profile
from showrunner.core.media import Episode, MediaItem
from showrunner.core.naming import (
    SUGGESTED_TEMPLATES,
    TOKENS,
    CustomKind,
    CustomToken,
    EpisodeCodeFormat,
    NamingContext,
    NamingOptions,
    PatternSource,
    Piece,
    PieceKind,
    Problem,
    Scope,
    SpaceStyle,
    TokenProblem,
    check_tokens,
    episode_code,
    parse,
    pieces,
    preview,
    write,
)
from showrunner.core.track import TrackKind
from showrunner.stages.metadata import (
    MetadataPlan,
    MetadataProblemKind,
    MetadataRefused,
    language_after,
    named_tracks,
    naming_context,
)
from showrunner.stages.tracks import PlannedTrack, TrackPlan, TracksOptions
from showrunner.tools.mkvtoolnix.propedit import Property
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.quick.tracks import item_number, item_title

TEMPLATES = (TITLE_TEMPLATE, *TRACK_TEMPLATES)
TRACK_KIND = dict(zip(TRACK_TEMPLATES, (TrackKind.VIDEO, TrackKind.AUDIO, TrackKind.SUBTITLE), strict=True))
_ICON = {"video_track_template": "video", "audio_track_template": "audio", "subtitle_track_template": "subs"}
# The token groups of the Tokens panel, in order; custom tokens come last.
_SCOPES = (Scope.ITEM, Scope.VIDEO, Scope.TRACK)
# The separators of the Tokens panel: key and the character a drop or click puts into the template. A separator is a
# character in the template's text, so the template, the checks and Apply see nothing new; `core.naming` knows which
# sides of it the join goes on. Each one inserts exactly what its label shows.
SEPARATORS = (
    ("dash", "-"),
    ("dot", "."),
    ("underscore", "_"),
    ("open_paren", "("),
    ("close_paren", ")"),
    ("open_bracket", "["),
    ("close_bracket", "]"),
    ("open_brace", "{"),
    ("close_brace", "}"),
)
_PADDINGS = (0, 2, 3)  # what a click on a number chip's format steps through
NEW_TOKEN = "token"


def problem_text(problem: Problem) -> str:
    return tr(f"problem.{problem.kind.value.replace('-', '_')}", detail=problem.detail)


def card_label(template: str) -> str:
    """The title card reads "File title" for shows and movies alike: the engine has one title template for both."""
    return tr("names.card.title" if template == TITLE_TEMPLATE else f"names.card.{TRACK_KIND[template].value}")


def token_label(name: str) -> str:
    return tr(f"token.{name}") if name in TOKENS else name


# Rail edits: each takes a template's text and gives the new text; a template with syntax problems stays as it is.


def _edit(template: str, change: Callable[[list[Piece]], None]) -> str:
    parsed = parse(template)
    if parsed.problems:
        return template
    parts = pieces(parsed)
    change(parts)
    return write(_without_empty_groups(parts))


def _without_empty_groups(parts: list[Piece]) -> list[Piece]:
    """The parts with the brackets of every group that holds no token directly taken away. Such a group is always
    shown, so the name is the same; a group whose last token was moved out would otherwise stay with no chip left to
    undo it."""
    i = 0
    while i < len(parts):
        if parts[i].kind is PieceKind.OPEN:
            close = _closing(parts, i)
            depth, direct = 0, False
            for part in parts[i + 1 : close]:
                depth += {PieceKind.OPEN: 1, PieceKind.CLOSE: -1}.get(part.kind, 0)
                direct = direct or (depth == 0 and part.kind is PieceKind.TOKEN)
            if not direct:
                del parts[close]
                del parts[i]
                continue
        i += 1
    return parts


def _closing(parts: Sequence[Piece], start: int) -> int:
    """The `CLOSE` piece of the group opened at `start`."""
    depth = 0
    for i in range(start, len(parts)):
        depth += {PieceKind.OPEN: 1, PieceKind.CLOSE: -1}.get(parts[i].kind, 0)
        if depth == 0:
            return i
    return len(parts) - 1


def _enclosing(parts: Sequence[Piece], at: int) -> int | None:
    """The `OPEN` piece of the innermost group around `at`, if any."""
    depth = 0
    for i in range(at - 1, -1, -1):
        if parts[i].kind is PieceKind.CLOSE:
            depth += 1
        elif parts[i].kind is PieceKind.OPEN:
            if depth == 0:
                return i
            depth -= 1
    return None


def _is(parts: Sequence[Piece], at: int, *kinds: PieceKind) -> bool:
    return 0 <= at < len(parts) and parts[at].kind in kinds


def insert_token(template: str, at: int, name: str) -> str:
    def change(parts: list[Piece]) -> None:
        parts.insert(max(0, min(at, len(parts))), Piece(PieceKind.TOKEN, name))

    return _edit(template, change)


def move_token(template: str, source: int, target: int) -> str:
    """Move the token at `source` to before the piece now at `target` (`len` for the end)."""

    def change(parts: list[Piece]) -> None:
        if not _is(parts, source, PieceKind.TOKEN, PieceKind.CHIP) or not 0 <= target <= len(parts):
            return
        piece = parts.pop(source)
        parts.insert(target - 1 if target > source else target, piece)

    return _edit(template, change)


def remove_piece(template: str, at: int) -> str:
    """Take out a token, a separator or a typed text."""

    def change(parts: list[Piece]) -> None:
        if _is(parts, at, PieceKind.TOKEN, PieceKind.CHIP, PieceKind.TEXT):
            del parts[at]

    return _edit(template, change)


def set_text(template: str, at: int, text: str) -> str:
    """Replace the typed text at `at`; empty text takes it out."""

    def change(parts: list[Piece]) -> None:
        if not _is(parts, at, PieceKind.TEXT):
            return
        if text:
            parts[at] = Piece(PieceKind.TEXT, text)
        else:
            del parts[at]

    return _edit(template, change)


def add_text(template: str, at: int, text: str) -> str:
    """Type text where there was none, before the piece at `at`."""

    def change(parts: list[Piece]) -> None:
        if text and 0 <= at <= len(parts):
            parts.insert(at, Piece(PieceKind.TEXT, text))

    return _edit(template, change)


def toggle_optional(template: str, at: int) -> str:
    """A token in a group leaves the group (its brackets go); one outside goes into a new group with the text or
    separator just before it (a dash before an episode title)."""

    def change(parts: list[Piece]) -> None:
        if not _is(parts, at, PieceKind.TOKEN):
            return
        if (opened := _enclosing(parts, at)) is not None:
            del parts[_closing(parts, opened)]
            del parts[opened]
            return
        start = at - 1 if _is(parts, at - 1, PieceKind.TEXT, PieceKind.CHIP) else at
        parts.insert(at + 1, Piece(PieceKind.CLOSE))
        parts.insert(start, Piece(PieceKind.OPEN))

    return _edit(template, change)


def cycle_padding(template: str, at: int) -> str:
    """A number token steps through no padding, two digits and three digits."""

    def change(parts: list[Piece]) -> None:
        piece = parts[at] if _is(parts, at, PieceKind.TOKEN) else None
        if piece is None or not (piece.text in TOKENS and TOKENS[piece.text].numeric):
            return
        step = _PADDINGS.index(piece.padding) + 1 if piece.padding in _PADDINGS else 0
        parts[at] = replace(piece, padding=_PADDINGS[step % len(_PADDINGS)])

    return _edit(template, change)


def rename_token(naming: NamingOptions, old: str, new: str) -> NamingOptions:
    """The options with every use of the custom token `old` named `new`: in the templates, in other tokens' templates
    and as a value map's key. Only to a valid name, since a template cannot hold another."""
    if old == new or check_tokens([CustomToken(new)]):
        return naming

    def renamed(template: str) -> str:
        def change(parts: list[Piece]) -> None:
            parts[:] = [replace(p, text=new) if p.kind is PieceKind.TOKEN and p.text == old else p for p in parts]

        return _edit(template, change) if any(p.text == old for p in pieces(parse(template))) else template

    tokens = [replace(t, text=renamed(t.text)) if t.kind is CustomKind.COMPOSITE else t for t in naming.custom_tokens]
    maps = {new if name == old else name: values for name, values in naming.value_maps.items()}
    templates = {name: renamed(getattr(naming, name)) for name in TEMPLATES}
    return replace(naming, custom_tokens=tokens, value_maps=maps, **templates)


def new_token_name(custom: Sequence[CustomToken]) -> str:
    taken = {t.name for t in custom}
    return next(f"{NEW_TOKEN}_{n}" for n in range(1, len(taken) + 2) if f"{NEW_TOKEN}_{n}" not in taken)


# What a template makes of a file


@dataclass(frozen=True, slots=True)
class Named:
    """One title or track name of a file: what it is now, what the template makes of it, and what it reads."""

    item: MediaItem
    track: PlannedTrack | None
    context: NamingContext
    now: str
    after: str  # empty when the template gives nothing, which leaves the name as it is
    text: str = ""  # the template it was named with


def named(
    items: Sequence[MediaItem], template: str, naming: NamingOptions, tracks: TracksOptions, untagged: str = ""
) -> list[Named]:
    """The batch's titles, or the names of the kept tracks of the template's kind, in file order. `untagged` is the
    language given to tracks without one, which a name reads as the plan does."""
    found = []
    for item in items:
        plan, options = named_tracks(item, tracks)
        entries: list[PlannedTrack | None] = (
            [None] if template == TITLE_TEMPLATE else [p for p in plan.kept if p.track.kind is TRACK_KIND[template]]
        )
        for track in entries:
            tag = language_after(track.track, tracks.rules, tracks.flags_from_names, untagged) if track else ""
            context = naming_context(item, naming, options, track, language=tag)
            now = item.file.title if track is None else track.track.name
            text = getattr(naming, template)
            found.append(Named(item, track, context, now, preview(text, context).text, text))
    return found


def _token_value(piece: Piece, context: NamingContext) -> str:
    return preview(write([piece]), context).text


def _walk(parts: Sequence[Piece], values: dict[int, str]) -> tuple[list[bool], list[tuple[bool, str]]]:
    """Which pieces are in the name, and the tokens that were empty: (in a group that was left out, name)."""
    kept = [True] * len(parts)
    losses: list[tuple[bool, str]] = []

    def visit(start: int, end: int, shown: bool) -> None:
        i = start
        while i < end:
            if parts[i].kind is PieceKind.OPEN:
                close = _closing(parts, i)
                direct, j = [], i + 1
                while j < close:
                    if parts[j].kind is PieceKind.OPEN:
                        j = _closing(parts, j) + 1
                        continue
                    direct.append(j)
                    j += 1
                empty = next((parts[k].text for k in direct if parts[k].kind is PieceKind.TOKEN and not values[k]), "")
                if shown and empty:
                    losses.append((True, empty))
                kept[i] = kept[close] = shown and not empty
                visit(i + 1, close, kept[i])
                i = close + 1
                continue
            kept[i] = shown
            if shown and parts[i].kind is PieceKind.TOKEN and not values[i]:
                losses.append((False, parts[i].text))
            i += 1

    visit(0, len(parts), True)
    return kept, losses


def segments(template: str, context: NamingContext) -> list[dict[str, object]]:
    """The name cut where each token's value lies, for underlining; the parts join to the engine's own result."""
    text = preview(template, context).text
    parsed = parse(template)
    if parsed.problems or not text:
        return [{"text": text, "token": False}] if text else []
    parts = pieces(parsed)
    values = {i: _token_value(p, context) for i, p in enumerate(parts) if p.kind is PieceKind.TOKEN}
    kept, _losses = _walk(parts, values)
    spans, cursor = [], 0
    for i, part in enumerate(parts):
        if not kept[i] or part.kind in (PieceKind.OPEN, PieceKind.CLOSE, PieceKind.CHIP):
            continue
        needle = values[i] if part.kind is PieceKind.TOKEN else part.text.strip()
        at = text.find(needle, cursor) if needle else -1
        if at < 0:
            continue
        if part.kind is PieceKind.TOKEN:
            spans.append((at, at + len(needle)))
        cursor = at + len(needle)
    found: list[dict[str, object]] = []
    last = 0
    for start, end in spans:
        if start > last:
            found.append({"text": text[last:start], "token": False})
        found.append({"text": text[start:end], "token": True})
        last = end
    if last < len(text):
        found.append({"text": text[last:], "token": False})
    return found


def loss_text(template: str, context: NamingContext, *, track: bool = False) -> str:
    """Why part of the name is missing in this file, worded; empty when nothing is."""
    parsed = parse(template)
    if parsed.problems:
        return ""
    parts = pieces(parsed)
    values = {i: _token_value(p, context) for i, p in enumerate(parts) if p.kind is PieceKind.TOKEN}
    _kept, losses = _walk(parts, values)
    if not losses:
        return ""
    in_group, name = losses[0]
    key = "names.loses_group" if in_group else "names.loses_token"
    return tr(f"{key}.track" if track else key, token=token_label(name))


# The rail


def _format(piece: Piece, context: NamingContext | None) -> str:
    """A number chip's format shown as the value it gives, "01" for two digits."""
    if piece.text not in TOKENS or not TOKENS[piece.text].numeric:
        return ""
    value = TOKENS[piece.text].read(context) if context is not None else None
    number = value if isinstance(value, int) else int(TOKENS[piece.text].example)
    return f"{number:0{piece.padding}d}" if piece.padding else str(number)


def rail(template: str, context: NamingContext | None, custom: Sequence[CustomToken]) -> list[dict[str, object]]:
    """The template's pieces as nested parts: chips, typed text and groups, with an empty text slot wherever two
    chips meet or a chip starts or ends a run, so text can be typed anywhere. `at` is a piece's index in the flat list,
    and a slot's `at` is where its text goes."""
    parsed = parse(template)
    if parsed.problems:
        return []
    parts = pieces(parsed)
    known = set(TOKENS) | {t.name for t in custom}

    def level(start: int, end: int, grouped: bool = False) -> list[dict[str, object]]:
        found: list[dict[str, object]] = []
        i = start
        while i < end:
            part = parts[i]
            if (not found or found[-1]["kind"] != "text") and part.kind is not PieceKind.TEXT:
                found.append({"kind": "slot", "at": i})
            if part.kind is PieceKind.OPEN:
                close = _closing(parts, i)
                found.append({"kind": "group", "at": i, "end": close, "parts": level(i + 1, close, True)})
                i = close + 1
                continue
            if part.kind is PieceKind.TEXT:
                found.append({"kind": "text", "at": i, "text": part.text})
            elif part.kind is PieceKind.CHIP:
                found.append({"kind": "separator", "at": i, "text": part.text})
            else:
                found.append(
                    {
                        "kind": "token",
                        "at": i,
                        "name": part.text,
                        "label": token_label(part.text),
                        "format": _format(part, context),
                        "numeric": bool(_format(part, context)),
                        "known": part.text in known,
                        "grouped": grouped,
                    }
                )
            i += 1
        if not found or found[-1]["kind"] != "text":
            found.append({"kind": "slot", "at": end})
        return found

    return level(0, len(parts))


# Counts from the live plan


def _kinds(file: FilePreview) -> dict[int, TrackKind]:
    stage = file.plan_for("tracks")
    plan = stage.plan if stage is not None and isinstance(stage.plan, TrackPlan) else None
    tracks = [k.track for k in plan.kept] if plan is not None else list(file.item.file.tracks)
    return {t.id: t.kind for t in tracks}


def card_counts(files: Sequence[FilePreview]) -> dict[str, int]:
    """How many titles and track names of each kind the live plan writes."""
    counts = dict.fromkeys(TEMPLATES, 0)
    by_kind = {kind: name for name, kind in TRACK_KIND.items()}
    for file in files:
        stage = file.plan_for("metadata")
        if stage is None or not isinstance(stage.plan, MetadataPlan):
            continue
        kinds = _kinds(file)
        for change in stage.plan.changes:
            if change.prop is Property.TITLE:
                counts[TITLE_TEMPLATE] += 1
            elif change.prop is Property.NAME and change.track_id is not None:
                counts[by_kind[kinds.get(change.track_id, TrackKind.SUBTITLE)]] += 1
    return counts


def blocked_lines(block: StageBlock | None, shown: str = "") -> list[str]:
    """Every reason the metadata stage plans nothing, worded and named by where it is; the problems of the template
    `shown` are left to the place that shows it."""
    if block is None:
        return []
    lines = [
        tr("names.blocked.template", card=card_label(name), problem=problem_text(problem))
        for name, problems in block.templates.items()
        if name != shown
        for problem in problems
    ]
    lines += [tr("names.blocked.token", token=p.name, problem=problem_text(p.problem)) for p in block.tokens]
    if block.language:
        lines.append(tr("names.blocked.language", language=block.language))
    return lines


# The place


@dataclass(frozen=True, slots=True)
class NamesInput:
    items: Sequence[MediaItem]
    focus: MediaItem | None
    media: Media
    naming: NamingOptions
    tracks: TracksOptions
    template: str  # the card the builder shows
    files: Sequence[FilePreview]  # the live plan, when it is current
    block: StageBlock | None  # why the metadata stage is not planned
    batch_title: str
    untagged: str = ""  # the language given to tracks without one
    # Each file's own options; a file missing here, or every file when it is empty, is named with the open place's.
    profiles: Mapping[Path, Profile] = field(default_factory=dict)


def _options_of(given: NamesInput, item: MediaItem) -> tuple[NamingOptions, TracksOptions, str]:
    """What a file is named with: its own options, which differ from the open place's where it or a place between
    them chose otherwise."""
    profile = given.profiles.get(item.file.path)
    if profile is None:
        return given.naming, given.tracks, given.untagged
    return profile.for_stage("naming"), profile.for_stage("tracks"), profile.for_stage("metadata").untagged_language


def _named_each(given: NamesInput, items: Sequence[MediaItem], template: str) -> list[Named]:
    return [entry for item in items for entry in named([item], template, *_options_of(given, item))]


def _file_label(item: MediaItem) -> str:
    return item_title(item) or item.file.path.stem


def place(given: NamesInput) -> dict[str, object]:
    naming, template = given.naming, given.template
    text = getattr(naming, template)
    counts = card_counts(given.files)
    focus = given.focus or (given.items[0] if given.items else None)
    entries = _named_each(given, given.items, template)
    focused = next((e for e in entries if e.item is focus), None)
    listed = any(e.text for e in entries)  # the open place's template, or one a file inside sets for itself
    cards = []
    for name in TEMPLATES:
        own = getattr(naming, name)
        # A template a file inside sets for itself counts too, so its names are listed and counted here.
        used = bool(own) or any(getattr(_options_of(given, item)[0], name) for item in given.items)
        stays = tr("names.card.stays.title" if name == TITLE_TEMPLATE else "names.card.stays.track")
        sample = next((e for e in _named_each(given, [focus], name) if e.after), None) if focus else None
        cards.append(
            {
                "key": name,
                "field": f"naming.{name}",  # the key of its mark in the window's `field_marks`
                "label": card_label(name),
                "icon": _ICON.get(name, "tv" if given.media is Media.EPISODES else "film"),
                "empty": not used,
                # A focused file that leaves the names as they are, by its own choice, reads as an empty card does.
                "sample": (sample.after if sample else stays) if used else "",
                "stays": stays,
                "count": counts[name],
                "count_text": _count_text(name, counts[name]) if used else "",
                "problem": bool(own and template_problems(naming, name))
                or bool(given.block and name in given.block.templates),
            }
        )
    suggested = SUGGESTED_TEMPLATES[template]
    suggestion = preview(suggested, focused.context).text if focused is not None else ""
    return {
        "cards": cards,
        "template": template,
        "title": card_label(template),
        "note": tr("names.card.title_note") if template == TITLE_TEMPLATE else "",
        "empty": not text,
        "editable": not parse(text).problems,
        "end": len(pieces(parse(text))),
        "text": text,
        "suggestion": suggestion,
        "space": space_choice(naming, template),
        "rail": rail(text, focused.context if focused else None, naming.custom_tokens),
        "problems": [problem_text(p) for p in template_problems(naming, template)] if text else [],
        # The picked template's own problems show under the rail.
        "blocked": blocked_lines(given.block, template),
        "result": _result(text, focused),
        "rows_title": tr("names.preview_on", batch=given.batch_title),
        "rows_count": _count_text(template, len(entries)),
        "rows": _rows(text, entries, focus, given.files) if listed else [],
        "listed": listed,
    }


def space_choice(naming: NamingOptions, template: str) -> dict[str, object]:
    """What the picked template joins its words with, with the choices."""
    return {
        "value": naming.space_for(template).value,
        "field": f"naming.{template.removesuffix('_template')}_space",
        "choices": [{"key": s.value, "label": tr(f"names.space.{s.value}")} for s in SpaceStyle],
    }


def _count_text(template: str, count: int) -> str:
    return tr_plural("names.count.titles" if template == TITLE_TEMPLATE else "names.count.names", count)


def _subject(entry: Named) -> str:
    file = _file_label(entry.item)
    if entry.track is None:
        return file
    return tr("names.track_of", track=entry.now or tr("names.no_name"), file=file)


def _result(text: str, entry: Named | None) -> dict[str, object]:
    if entry is None or not text:
        return {"label": "", "segments": [], "stays": False}
    parts = segments(entry.text, entry.context)  # the template the file is named with
    if not parts:
        return {"label": tr("names.result.stays", name=_subject(entry)), "segments": [], "stays": True}
    return {"label": tr("names.result.becomes", name=_subject(entry)), "segments": parts, "stays": False}


def not_written(file: FilePreview) -> str:
    """Why the live plan writes no names on this file, worded; empty when it writes them. A blocked stage is
    explained once, above the rows."""
    stage = file.plan_for("metadata")
    if stage is None:
        return tr("names.why.program")
    if stage.state is PlanState.BLOCKED:
        return ""
    if isinstance(stage.plan, MetadataRefused):
        kinds = {problem.kind for problem in stage.plan.problems}
        if MetadataProblemKind.NOT_MATROSKA in kinds:
            return tr("names.why.not_matroska")
        if MetadataProblemKind.IDS_NOT_FROM_MKVMERGE in kinds:
            return tr("names.why.no_ids")
        return tr("names.why.refused")
    if file.outcome in (FileOutcome.NEEDS_REMUX, FileOutcome.MISSING):
        return tr("names.why.needs_remux")
    return ""


def _planned(file: FilePreview, entry: Named) -> bool:
    """Whether the live plan writes this title or track name."""
    stage = file.plan_for("metadata")
    if stage is None or not isinstance(stage.plan, MetadataPlan) or not_written(file):
        return False
    if entry.track is None:
        return any(c.prop is Property.TITLE for c in stage.plan.changes)
    track_id = entry.track.track.id
    return any(c.prop is Property.NAME and c.track_id == track_id for c in stage.plan.changes)


def _rows(text: str, entries: Sequence[Named], focus: MediaItem | None, files: Sequence[FilePreview]) -> list[dict]:
    """The batch before and after. With a current plan a row is a change only when the plan writes it, and says why
    not; before the plan arrives it follows the template. A part left out is noted only where it sets a file apart:
    when most files lack it, as most tracks lack flags, it is no news."""
    by_path = {f.item.file.path: f for f in files}
    losses = [loss_text(e.text or text, e.context, track=e.track is not None) for e in entries]
    usual = Counter(losses).most_common(1)[0][0] if losses else ""
    rows = []
    for entry, loss in zip(entries, losses, strict=True):
        file = by_path.get(entry.item.file.path)
        differs = bool(entry.after) and entry.after != entry.now
        why = not_written(file) if file is not None and differs else ""
        changed = differs and (file is None or _planned(file, entry))
        now = entry.now or tr("names.now_empty.title" if entry.track is None else "names.now_empty.track")
        rows.append(
            {
                "number": item_number(entry.item),
                "now": now,
                "now_empty": not entry.now,
                "after": entry.after or now,
                "changed": changed,
                "note": why or (loss if loss != usual else ""),
                "path": str(entry.item.file.path),
                "focused": entry.item is focus,
            }
        )
    return rows


# The Tokens panel


def _panel_context(given: NamesInput) -> tuple[NamingContext | None, NamingContext | None]:
    """The focused file's context for its own tokens, and that of its first track of the card's kind for track
    tokens (none on the title card)."""
    focus = given.focus or (given.items[0] if given.items else None)
    if focus is None:
        return None, None
    entries = _named_each(given, [focus], given.template)
    title = _named_each(given, [focus], TITLE_TEMPLATE)[0].context
    track = entries[0].context if entries and given.template != TITLE_TEMPLATE else None
    return title, track


def _matches(query: str, *texts: str) -> bool:
    folded = query.strip().casefold()
    return not folded or any(folded in t.casefold() for t in texts)


# Value maps: a token's value, exactly as read, rewritten ("Dolby Digital Plus 5.1" written as "DDP 5.1").


def map_rows(naming: NamingOptions, name: str) -> list[dict[str, str]]:
    return [{"read": read, "written": written} for read, written in naming.value_maps.get(name, {}).items()]


def set_map_row(naming: NamingOptions, name: str, row: int, read: str, written: str) -> NamingOptions:
    """`naming` with row `row` of `name`'s value map set; a row past the end is added, a row left with nothing
    read is removed, and a map left empty goes with it. A read value already in the map keeps its first place."""
    rows = [(r["read"], r["written"]) for r in map_rows(naming, name)]
    if row < len(rows):
        rows[row] = (read, written)
    elif read:
        rows.append((read, written))
    values: dict[str, str] = {}
    for key, value in rows:
        if key:
            values.setdefault(key, value)
    maps = {token: dict(entries) for token, entries in naming.value_maps.items() if token != name}
    if values:
        maps[name] = values
    return replace(naming, value_maps=maps)


def tokens(given: NamesInput, query: str, editing: int, builtin: str = "") -> dict[str, object]:
    """The built-in tokens by scope and the user's own, each with its value on the focused file; the token open in
    the editor (a custom token by index, or a built-in one by name) with its value map."""
    title, track = _panel_context(given)
    custom = given.naming.custom_tokens
    problems = check_tokens(custom, given.naming.value_maps)

    def value(name: str, scope: Scope | None, mapped: bool = True) -> str:
        context = track if scope is Scope.TRACK else title
        if context is None:
            return ""
        # The raw value is what a row reads, so neither the replacements nor the space choice apply to it.
        raw = replace(context, value_maps={}, space=SpaceStyle.SPACE)
        return preview(f"{{{name}}}", context if mapped else raw).text

    groups = []
    # First, so the few separators are in view without scrolling past the long token list.
    marks = [
        {"name": key, "label": tr(f"tokens.sep.{key}.label"), "text": text, "tip": tr(f"tokens.sep.{key}.tip")}
        for key, text in SEPARATORS
    ]
    if found := [m for m in marks if _matches(query, m["name"], m["label"], m["tip"])]:
        groups.append({"key": "separator", "label": tr("tokens.group.separator"), "tokens": found})
    for scope in _SCOPES:
        entries = [
            {"name": t.name, "label": token_label(t.name), "value": value(t.name, scope), "index": -1}
            for t in TOKENS.values()
            if t.scope is scope
            and not (t.track_templates_only and given.template == TITLE_TEMPLATE)
            and _matches(query, t.name, token_label(t.name))
        ]
        if entries:
            groups.append({"key": scope.value, "label": tr(f"tokens.group.{scope.value}"), "tokens": entries})
    mine = [
        {"name": t.name, "label": t.name, "value": value(t.name, None), "index": i}
        for i, t in enumerate(custom)
        if _matches(query, t.name)
    ]
    groups.append({"key": "custom", "label": tr("tokens.group.custom"), "tokens": mine})
    if 0 <= editing < len(custom):
        name, scope = custom[editing].name, None
        editor = _editor(given, custom[editing], editing, problems)
    elif builtin in TOKENS:
        name, scope = builtin, TOKENS[builtin].scope
        focus = given.focus or (given.items[0] if given.items else None)
        editor = {
            "index": -1,
            "name": builtin,
            "label": token_label(builtin),
            "value": value(builtin, scope),
            "value_label": tr("tokens.editor.on_file", file=_file_label(focus)) if focus is not None else "",
            **(_code_formats(given.naming, focus) if builtin == "episode_code" else {}),
        }
    else:
        return {"groups": groups, "editor": {}}
    raw = value(name, scope, mapped=False)
    editor |= {
        "maps": [*map_rows(given.naming, name), {"read": "", "written": ""}],
        "raw": tr("tokens.maps.read_here", value=raw) if raw else "",
    }
    return {"groups": groups, "editor": editor}


def _code_formats(naming: NamingOptions, focus: MediaItem | None) -> dict[str, object]:
    """The spellings of the episode code, each shown on the focused episode, and what a two-episode file reads."""
    episode = focus.identity if focus is not None and isinstance(focus.identity, Episode) else None
    season, first, last = (episode.season, episode.episode, episode.last_episode) if episode else (1, 1, None)
    return {
        "formats": [
            {"key": f.value, "label": episode_code(f, season, first, last), "checked": f is naming.episode_code_format}
            for f in EpisodeCodeFormat
        ],
        "formats_label": tr("tokens.code.format"),
        "formats_note": tr("tokens.code.note", example=episode_code(naming.episode_code_format, 1, 1, 2)),
    }


def _editor(given: NamesInput, token: CustomToken, index: int, problems: list[TokenProblem]) -> dict[str, object]:
    first = next((i for i, t in enumerate(given.naming.custom_tokens) if t.name == token.name), index)
    own = [p for p in problems if p.name == token.name] if first == index else []
    contexts = [
        named([item], TITLE_TEMPLATE, given.naming, given.tracks, given.untagged)[0].context for item in given.items
    ]
    values = [preview(f"{{{token.name}}}", c).text for c in contexts]
    focus = given.focus or (given.items[0] if given.items else None)
    on_focus = next((v for item, v in zip(given.items, values, strict=True) if item is focus), "")
    found = sum(bool(v) for v in values)
    return {
        "index": index,
        "name": token.name,
        "kind": token.kind.value,
        "text": token.text,
        "source": token.source.value,
        "name_problems": [problem_text(p.problem) for p in own if p.part.value == "name"],
        "text_problems": [problem_text(p.problem) for p in own if p.part.value == "text"],
        "text_label": tr(f"tokens.editor.text.{token.kind.value}"),
        "value": on_focus,
        "value_label": tr("tokens.editor.on_file", file=_file_label(focus)) if focus is not None else "",
        "found": tr("tokens.editor.found", found=found, total=len(values)),
    }


KINDS = tuple(kind.value for kind in (CustomKind.CONSTANT, CustomKind.PATTERN, CustomKind.COMPOSITE))
SOURCES = tuple(source.value for source in PatternSource)
