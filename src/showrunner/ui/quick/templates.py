"""The Names place and the Tokens panel: the templates of the open place, the builder rail of the picked one, its custom
tokens and the value maps of every token. Each edit ends in the open place's own naming options."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, Signal

from showrunner.app.jobs.blocked import blocked_stages
from showrunner.app.jobs.groups import TITLE_TEMPLATE
from showrunner.core.naming import (
    SUGGESTED_TEMPLATES,
    TOKENS,
    CustomKind,
    CustomToken,
    EpisodeCodeFormat,
    NamingOptions,
    PatternSource,
    SpaceStyle,
    parse,
    pieces,
)
from showrunner.ui.quick import names as rail
from showrunner.ui.quick.workspace import Workspace


class Templates(QObject):
    names_changed = Signal()  # what the Names place or the Tokens panel shows changed

    def __init__(self, workspace: Workspace, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._template = TITLE_TEMPLATE  # the template the Names builder shows
        self._token_query = ""
        self._editing = -1  # the custom token open in the Tokens panel's editor
        self._editing_builtin = ""  # or the built-in token open there, for its value map
        self._names: dict[str, Any] | None = {}  # what the Names place and the Tokens panel read; None until read
        self._stale = False  # Names changed while it was hidden
        workspace.place_left.connect(self._close_editor)
        workspace.rebuilt.connect(self.refresh)
        workspace.place_shown.connect(self._on_place_shown)

    def _close_editor(self) -> None:
        """The open token belongs to the profile of the place that was left."""
        self._editing, self._editing_builtin = -1, ""

    def _naming(self) -> NamingOptions:
        assert self._workspace.key is not None
        return self._workspace.batches.profile(self._workspace.key).for_stage("naming")

    def _set_naming(self, options: NamingOptions) -> None:
        workspace = self._workspace
        if workspace.key is None or workspace.locked or options == self._naming():
            self.refresh()  # a locked batch's rail shows its template again
            return
        workspace.set_options("naming", options)

    def _set_template(self, text: str) -> None:
        if self._workspace.key is not None:
            self._set_naming(replace(self._naming(), **{self._template: text}))

    def _template_text(self) -> str:
        return getattr(self._naming(), self._template) if self._workspace.key is not None else ""

    @property
    def names(self) -> dict[str, Any]:
        """The template cards, the builder rail of the picked one, its result and the batch before and after."""
        return self._names_built().get("place", {})

    @property
    def tokens(self) -> dict[str, Any]:
        return self._names_built().get("tokens", {"groups": [], "editor": {}})

    def _names_built(self) -> dict[str, Any]:
        if self._names is None:
            self._names = self._build_names()
        return self._names

    def pick_template(self, template: str) -> None:
        if template in rail.TEMPLATES and template != self._template:
            self._template = template
            self.refresh()

    def start_template(self, template: str) -> None:
        """Pick a card and fill its empty template with the suggested one."""
        if template not in rail.TEMPLATES:
            return
        self._template = template
        if self._template_text():
            self.refresh()
            return
        self._set_template(SUGGESTED_TEMPLATES[template])

    def clear_template(self) -> None:
        self._set_template("")

    def rail_insert(self, at: int, name: str) -> None:
        self._set_template(rail.insert_token(self._template_text(), at, name))

    def rail_append(self, name: str) -> None:
        text = self._template_text()
        self._set_template(rail.insert_token(text, len(pieces(parse(text))), name))

    def rail_append_text(self, text: str) -> None:
        """A separator clicked in the panel: typed text at the end of the template."""
        template = self._template_text()
        self._set_template(rail.add_text(template, len(pieces(parse(template))), text))

    def rail_move(self, source: int, target: int) -> None:
        self._set_template(rail.move_token(self._template_text(), source, target))

    def rail_remove(self, at: int) -> None:
        self._set_template(rail.remove_piece(self._template_text(), at))

    def rail_set_text(self, at: int, text: str) -> None:
        self._set_template(rail.set_text(self._template_text(), at, text))

    def rail_add_text(self, at: int, text: str) -> None:
        self._set_template(rail.add_text(self._template_text(), at, text))

    def rail_optional(self, at: int) -> None:
        self._set_template(rail.toggle_optional(self._template_text(), at))

    def rail_padding(self, at: int) -> None:
        self._set_template(rail.cycle_padding(self._template_text(), at))

    def set_space(self, style: str) -> None:
        """What the picked template joins its words with."""
        if self._workspace.key is not None and style in SpaceStyle:
            field = self._template.removesuffix("_template") + "_space"
            self._set_naming(replace(self._naming(), **{field: SpaceStyle(style)}))

    def set_episode_code_format(self, style: str) -> None:
        """How the Episode code token is spelled, in every template."""
        if self._workspace.key is not None and style in EpisodeCodeFormat:
            self._set_naming(replace(self._naming(), episode_code_format=EpisodeCodeFormat(style)))

    @property
    def token_query(self) -> str:
        return self._token_query

    @token_query.setter
    def token_query(self, text: str) -> None:
        if text != self._token_query:
            self._token_query = text
            self.refresh()

    def custom(self) -> list[CustomToken]:
        """The open place's custom tokens."""
        return list(self._naming().custom_tokens) if self._workspace.key is not None else []

    def add_token(self) -> None:
        """A new text token with a free name, open in the editor."""
        if self._workspace.key is None:
            return
        custom = self.custom()
        self._editing, self._editing_builtin = len(custom), ""
        self._set_naming(replace(self._naming(), custom_tokens=[*custom, CustomToken(rail.new_token_name(custom))]))

    def edit_token(self, index: int) -> None:
        """Open a custom token in the editor; -1 closes it."""
        self._editing = index if 0 <= index < len(self.custom()) else -1
        self._editing_builtin = ""
        self.refresh()

    def edit_builtin(self, name: str) -> None:
        """Open a built-in token in the editor, for its value map; "" closes it."""
        self._editing, self._editing_builtin = -1, name if name in TOKENS else ""
        self.refresh()

    def set_value_map(self, name: str, row: int, read: str, written: str) -> None:
        """Set one row of a token's value map: what the token reads, and what is written instead."""
        if self._workspace.key is not None and not self._workspace.locked and row >= 0:
            self._set_naming(rail.set_map_row(self._naming(), name, row, read, written))

    def _change_token(self, index: int, **changes: Any) -> None:
        custom = self.custom()
        if 0 <= index < len(custom):
            custom[index] = replace(custom[index], **changes)
            self._set_naming(replace(self._naming(), custom_tokens=custom))

    def rename_token(self, index: int, name: str) -> None:
        """Rename a custom token, and its uses in the templates, other tokens and value maps with it."""
        custom = self.custom()
        if not 0 <= index < len(custom) or name == custom[index].name:
            return
        naming = rail.rename_token(self._naming(), custom[index].name, name)
        tokens = list(naming.custom_tokens)
        tokens[index] = replace(tokens[index], name=name)
        self._set_naming(replace(naming, custom_tokens=tokens))

    def set_token_kind(self, index: int, kind: str) -> None:
        if kind in rail.KINDS:
            self._change_token(index, kind=CustomKind(kind))

    def set_token_text(self, index: int, text: str) -> None:
        self._change_token(index, text=text)

    def set_token_source(self, index: int, source: str) -> None:
        if source in rail.SOURCES:
            self._change_token(index, source=PatternSource(source))

    def remove_token(self, index: int) -> None:
        custom = self.custom()
        if not 0 <= index < len(custom):
            return
        self._editing = -1
        name, kept = custom[index].name, custom[:index] + custom[index + 1 :]
        maps = self._naming().value_maps
        # A value map of a token that is gone would block Metadata, with nothing here to fix it.
        if all(t.name != name for t in kept):
            maps = {token: values for token, values in maps.items() if token != name}
        self._set_naming(replace(self._naming(), custom_tokens=kept, value_maps=maps))

    def _on_place_shown(self) -> None:
        if self._workspace.place == "names" and self._stale:
            self.refresh()

    def refresh(self) -> None:
        """Build what Names and Tokens show; QML hears of it only when it changed, so a plan that arrives while text
        is typed does not rebuild the rail under the cursor. While Names is hidden nothing is built: it is built when
        read, and QML hears of it on switching to Names."""
        if self._workspace.place != "names":
            self._names = None
            self._stale = True
            return
        self._stale = False
        built = self._build_names()
        if built != self._names:
            self._names = built
            self.names_changed.emit()

    def _build_names(self) -> dict[str, Any]:
        workspace = self._workspace
        built: dict[str, Any] = {}
        if workspace.key is not None:
            profile = workspace.batches.profile(workspace.key)
            given = rail.NamesInput(
                items=workspace.items,
                focus=workspace.focus,
                media=workspace.key.media,
                naming=profile.for_stage("naming"),
                tracks=profile.for_stage("tracks"),
                template=self._template,
                files=workspace.current_files(),
                block=blocked_stages(profile).get("metadata"),
                batch_title=workspace.heading().title,
                untagged=profile.for_stage("metadata").untagged_language,
                profiles=workspace.batches.file_profiles(workspace.items, workspace.key),
            )
            built = {
                "place": rail.place(given),
                "tokens": rail.tokens(given, self._token_query, self._editing, self._editing_builtin),
            }
        return built
