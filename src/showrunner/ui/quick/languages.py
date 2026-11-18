"""The language picker behind a chip's badge and the Names place: the lists, the tag as it is built and its check.

The window hands the picker what it needs (the tag now, the languages of the batch, the codes MKVToolNix accepts) and
takes the answer back through `applied`; the picker knows nothing of chips or rules. QML draws `state`, the three
list models and sends every click and key to a slot.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from typing import Any

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
    Slot,
)

from showrunner.app.languages import LanguageIndex, TagProblem, check_tag
from showrunner.core.language import Language, languages, regions, scripts
from showrunner.ui.i18n.catalog import tr

_NAME, _CODE, _DETAIL = (Qt.ItemDataRole.UserRole + n for n in (1, 2, 3))


class EntryModel(QAbstractListModel):
    """The rows of one list, as (code, name, detail): a plain model, so a list of thousands is a `ListView` over it
    and only the rows on screen are made."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, str, str]] = []

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802  # Qt's name
        return {_NAME: QByteArray(b"name"), _CODE: QByteArray(b"code"), _DETAIL: QByteArray(b"detail")}

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008, N802  # Qt's name
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        code, name, detail = self._rows[index.row()]
        return {_NAME: name, _CODE: code, _DETAIL: detail, Qt.ItemDataRole.DisplayRole: name}.get(role)

    def set_rows(self, rows: Sequence[tuple[str, str, str]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    @Slot(str, result=int)
    def row_of(self, code: str) -> int:
        return next((n for n, row in enumerate(self._rows) if row[0] == code), -1)


def _fits(row: tuple[str, str, str], text: str) -> bool:
    code, name, _ = row
    return all(w in name.casefold() or code.casefold().startswith(w) for w in text.casefold().split())


class LanguagePicker(QObject):
    """One picker for the window: `begin` opens it on a tag, `applied(target, tag)` answers. `target` says what the
    answer is for, as the window gave it to `begin`."""

    changed = Signal()
    opened = Signal()
    applied = Signal(str, str)

    def __init__(
        self,
        known_codes: Callable[[], frozenset[str] | None] = lambda: None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._known = known_codes
        self._index = LanguageIndex.of(languages())
        self._languages = EntryModel(self)
        self._regions = EntryModel(self)
        self._scripts = EntryModel(self)
        self._region_rows = [(code, name, code) for code, name in regions()]
        self._script_rows = [(code, name, code) for code, name in scripts()]
        self._target = ""
        self._title = ""
        self._batch: Collection[str] = ()
        self._clearable = False
        self._query = ""
        self._language = ""  # the 3-letter code of the chosen language
        self._region = ""
        self._script = ""
        self._rest = ""
        self._typed = ""

    # The lists

    @Property(QObject, constant=True)
    def language_model(self) -> QObject:
        return self._languages

    @Property(QObject, constant=True)
    def region_model(self) -> QObject:
        return self._regions

    @Property(QObject, constant=True)
    def script_model(self) -> QObject:
        return self._scripts

    def refresh_languages(self) -> None:
        """Take the list again, after MKVToolNix's extra codes were added to it or taken away."""
        self._index = LanguageIndex.of(languages())
        self._show_languages()

    def _show_languages(self) -> None:
        found = self._index.search(self._query, self._batch)
        self._languages.set_rows([(row.code, row.name, ", ".join(row.codes)) for row in found])

    # Opening and closing

    def begin(self, target: str, title: str, tag: str, batch: Collection[str] = (), *, clearable: bool = False) -> None:
        """Open the picker on `tag` (empty for none). `batch` holds the 3-letter codes of the languages the batch has,
        which the list puts first; `clearable` offers going back to leaving the language as it is."""
        self._target, self._title, self._batch, self._clearable = target, title, batch, clearable
        self._query = ""
        self._set_tag(Language.parse(tag) if tag else None)
        self._typed = ""
        self._show_languages()
        self._regions.set_rows(self._region_rows)
        self._scripts.set_rows(self._script_rows)
        self.changed.emit()
        self.opened.emit()

    def _set_tag(self, language: Language | None) -> None:
        self._language = language.alpha3 if language else ""
        self._region = (language.region or "") if language else ""
        self._script = (language.script or "") if language else ""
        self._rest = language.rest if language else ""

    # The tag as it is built

    def _built(self) -> Language | None:
        if not self._language:
            return None
        return Language(self._language, self._region or None, self._script or None, self._rest)

    def _check(self) -> dict[str, str]:
        """The line under the typed field: what the tag is, or what is wrong with it."""
        if not self._typed.strip():
            return {"state": "none", "text": ""}
        result = check_tag(self._typed, self._known())
        if result.problem is TagProblem.NOT_A_TAG:
            return {"state": "error", "text": tr("language.check.not_a_tag")}
        assert result.language is not None
        if result.problem is TagProblem.UNKNOWN_TO_MKVTOOLNIX:
            return {"state": "warn", "text": tr("language.check.unknown", code=result.language.alpha3)}
        return {"state": "ok", "text": result.language.display}

    @Property("QVariantMap", notify=changed)
    def state(self) -> dict[str, Any]:
        built = self._built()
        check = self._check()
        return {
            "title": self._title,
            "tag": built.ietf if built else "",
            "name": built.display if built else "",
            "language": self._language,
            "region": self._region,
            "script": self._script,
            "typed": self._typed,
            "check": check,
            "can_apply": built is not None and check["state"] != "error",
            "clearable": self._clearable,
            "query": self._query,
        }

    # What the user does

    @Slot(str)
    def set_query(self, text: str) -> None:
        self._query = text
        self._show_languages()
        self.changed.emit()

    @Slot(str)
    def set_region_query(self, text: str) -> None:
        self._regions.set_rows([row for row in self._region_rows if _fits(row, text)])

    @Slot(str)
    def set_script_query(self, text: str) -> None:
        self._scripts.set_rows([row for row in self._script_rows if _fits(row, text)])

    @Slot(str)
    def select_language(self, code: str) -> None:
        self._language, self._typed = code, ""
        self.changed.emit()

    @Slot(str)
    def select_region(self, code: str) -> None:
        """Pick a region, or take it off when it is the one already picked."""
        self._region = "" if self._region == code else code
        self._typed = ""
        self.changed.emit()

    @Slot(str)
    def select_script(self, code: str) -> None:
        self._script = "" if self._script == code else code
        self._typed = ""
        self.changed.emit()

    @Slot(str)
    def set_typed(self, text: str) -> None:
        """A tag typed in: when it is one, the picks follow it, so the lists show where it lies."""
        self._typed = text
        if (language := Language.parse(text)) is not None:
            self._set_tag(language)
        self.changed.emit()

    @Slot()
    def apply(self) -> None:
        if self.state["can_apply"]:
            self.applied.emit(self._target, self.state["tag"])

    @Slot()
    def clear(self) -> None:
        """Give the language back to the file: the answer is an empty tag."""
        self.applied.emit(self._target, "")
