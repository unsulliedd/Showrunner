"""The cleanup rule editor: rule sets, the rules of a set, one rule, and a live test of the set against sample text or
the loaded subtitle. Built-in sets are read only (their rules can be paused, and a set can be duplicated into one of the
user's own); an own set is written as cleanit YAML on every change that leaves it valid.

QML draws `view` and sends every edit to a slot; the draft, its problems and what is saved live here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from showrunner.app.rules import RULES, RuleStore
from showrunner.core.cue import Cue
from showrunner.core.language import Language
from showrunner.tools.cleanit import (
    OCR_EXTRA,
    Imported,
    Match,
    NotSubtitleEditError,
    RuleBook,
    RuleDef,
    RuleError,
    RuleKind,
    RuleSet,
    check_rule,
    clean_cues,
    dump_set,
    language_of,
    read_file,
    valid_name,
)
from showrunner.tools.cleanit.engine import compile_sets
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.quick.lines import clock, rule_label
from showrunner.ui.quick.subtitles import set_label, set_languages

_NEW_RULE = "New rule"
_SHOWN = 400  # test lines drawn at most
_ENGLISH = Language("eng")
type Loaded = Callable[[], tuple[list[Cue], Language | None, str] | None]


class CleanupEditor(QObject):
    changed = Signal()
    opened = Signal()
    saved = Signal()  # an own set or a pause was written: plans that clean must be made again

    def __init__(
        self,
        loaded: Loaded,
        locked: Callable[[], bool],
        parent: QObject | None = None,
        *,
        rules: RuleStore = RULES,
    ) -> None:
        super().__init__(parent)
        self._loaded = loaded
        self._locked = locked
        self._rules = rules
        self._set = ""
        self._rule = 0
        self._draft: RuleSet | None = None  # the selected own set as edited; written once it is valid
        self._error = ""
        self._source = "sample"
        self._sample = ""
        self._only_mine = False
        self._show_yaml = False
        self._import: tuple[str, Imported] | None = None
        self._import_error = ""
        self._built: dict[str, Any] | None = None

    # What QML reads

    @Property("QVariantMap", notify=changed)
    def view(self) -> dict[str, Any]:
        if self._built is None:
            self._built = self._build()
        return self._built

    def _changed(self) -> None:
        self._built = None
        self.changed.emit()

    @Slot(str)
    def open(self, name: str = "") -> None:
        """Open on the set `name`, or the first set when it is empty or gone."""
        book = self._rules.book()
        self._set = name if name in book.sets else next(iter(book.sets), "")
        self._select_set_state(book)
        self._import = None
        self._import_error = ""
        self._changed()
        self.opened.emit()

    # Selecting

    @Slot(str)
    def select_set(self, name: str) -> None:
        self._set = name
        self._select_set_state(self._rules.book())
        self._changed()

    @Slot(int)
    def select_rule(self, index: int) -> None:
        self._rule = index
        self._draft_for_selected()  # an unsaved change to the other rule is dropped with the draft
        self._seed_sample()
        self._changed()

    def _select_set_state(self, book: RuleBook) -> None:
        self._rule = 0
        self._error = ""
        self._show_yaml = False
        self._draft = None
        self._draft_for_selected(book)
        self._seed_sample()

    def _draft_for_selected(self, book: RuleBook | None = None) -> None:
        book = book or self._rules.book()
        found = book.sets.get(self._set)
        self._error = ""
        self._draft = self._ordered(found) if found is not None and not found.builtin else None

    @staticmethod
    def _ordered(rule_set: RuleSet) -> RuleSet:
        """The rules in the order they run, so the list and the numbers written to the file agree."""
        return replace(rule_set, rules=tuple(sorted(rule_set.rules, key=lambda r: -r.priority)))

    def _current(self) -> RuleSet | None:
        if self._draft is not None and self._draft.name == self._set:
            return self._draft
        found = self._rules.book().sets.get(self._set)
        return self._ordered(found) if found is not None else None

    def _rule_now(self) -> RuleDef | None:
        current = self._current()
        return current.rules[self._rule] if current is not None and 0 <= self._rule < len(current.rules) else None

    def _seed_sample(self) -> None:
        rule = self._rule_now()
        self._sample = "\n\n".join(e.before.strip() for e in rule.examples) if rule is not None else ""

    # Editing an own set

    def _editable(self) -> bool:
        current = self._current()
        return current is not None and not current.builtin and not self._locked()

    def _put(self, rule_set: RuleSet) -> None:
        """Keep an edited own set, and write it when every rule of it is valid."""
        self._draft = rule_set
        self._error = self._problem(rule_set)
        if not self._error:
            self._rules.save(rule_set)
            self.saved.emit()
        self._changed()

    @staticmethod
    def _problem(rule_set: RuleSet) -> str:
        names = [r.name for r in rule_set.rules]
        for rule in rule_set.rules:
            if not rule.name.strip():
                return tr("cleanup.error.name")
            if names.count(rule.name) > 1:
                return tr("cleanup.error.name_taken", name=rule.name)
            if message := check_rule(rule, rule_set.aliases):
                return f"{rule.name}: {message}"
            if any(Language.parse(tag) is None for tag in rule.languages):
                return tr("cleanup.error.language", rule=rule.name)
        return ""

    @Slot(str, str)
    def set_field(self, field: str, value: str) -> None:
        """One field of the selected rule, as typed."""
        rule, current = self._rule_now(), self._current()
        if rule is None or current is None or not self._editable():
            return
        changes: dict[str, Any] = {
            "name": lambda: {"name": value.strip()},
            "kind": lambda: {"kind": RuleKind(value)},
            "match": lambda: {"match": Match(value)},
            "patterns": lambda: {"patterns": tuple(line for line in value.split("\n") if line.strip())},
            "replacement": lambda: {"replacement": value if rule.replacement is not None else None},
            "languages": lambda: {
                "languages": tuple(t.strip() for t in value.replace(";", ",").split(",") if t.strip())
            },
        }
        if field == "action":
            changes["action"] = lambda: {"replacement": "" if value == "replace" else None}
        if field not in changes:
            return
        rules = list(current.rules)
        rules[self._rule] = replace(rule, **changes[field]())
        self._put(replace(current, rules=tuple(rules)))

    @Slot(int)
    def toggle_pause(self, index: int) -> None:
        """Pause or unpause a rule: an own rule in its file, a built-in rule in the file that pauses by name."""
        current = self._current()
        if current is None or self._locked() or not 0 <= index < len(current.rules):
            return
        rule = current.rules[index]
        if current.builtin:
            self._rules.pause_builtin(rule.name, not rule.paused)
            self.saved.emit()
            self._changed()
            return
        rules = list(current.rules)
        rules[index] = replace(rule, paused=not rule.paused)
        self._put(replace(current, rules=tuple(rules)))

    @Slot()
    def add_rule(self) -> None:
        current = self._current()
        if current is None or not self._editable():
            return
        names = {r.name for r in current.rules}
        name, number = _NEW_RULE, 1
        while name in names:
            number += 1
            name = f"{_NEW_RULE} {number}"
        # Paused and empty of effect until it is written, so a rule half made never touches a subtitle.
        fresh = RuleDef(name, (tr("cleanup.rule.starter"),), RuleKind.TEXT, replacement="", paused=True)
        self._rule = len(current.rules)
        self._put(replace(current, rules=(*current.rules, fresh)))
        self._seed_sample()

    @Slot(int)
    def remove_rule(self, index: int) -> None:
        current = self._current()
        if current is None or not self._editable() or len(current.rules) < 2 or not 0 <= index < len(current.rules):
            return  # a set file holds at least one rule
        rules = list(current.rules)
        del rules[index]
        self._rule = min(self._rule, len(rules) - 1)
        self._put(replace(current, rules=tuple(rules)))
        self._seed_sample()

    @Slot(int, int)
    def move_rule(self, index: int, by: int) -> None:
        current = self._current()
        target = index + by
        if (
            current is None
            or not self._editable()
            or not (0 <= index < len(current.rules) and 0 <= target < len(current.rules))
        ):
            return
        rules = list(current.rules)
        rules[index], rules[target] = rules[target], rules[index]
        # The order a rule runs in is its priority, so the new order is written as priorities.
        rules = [replace(r, priority=len(rules) - n) for n, r in enumerate(rules)]
        self._rule = target
        self._put(replace(current, rules=tuple(rules)))

    # Sets

    def _name_error(self, name: str) -> str:
        if problem := valid_name(name):
            return tr(f"cleanup.error.set_{problem}")
        if name.casefold() in {existing.casefold() for existing in self._rules.book().sets}:
            return tr("cleanup.error.set_exists")
        return ""

    @Slot(str, result=str)
    def new_set(self, name: str) -> str:
        """A new own set with one paused rule to start from. The answer is what is wrong with the name, or empty."""
        name = name.strip()
        if self._locked():
            return tr("cleanup.error.locked")
        if error := self._name_error(name):
            return error
        starter = RuleDef(_NEW_RULE, (tr("cleanup.rule.starter"),), RuleKind.TEXT, replacement="", paused=True)
        self._rules.save(RuleSet(name, (starter,)))
        self.saved.emit()
        self.select_set(name)
        return ""

    @Slot(str, result=str)
    def duplicate_set(self, name: str) -> str:
        """An own copy of the selected set, to edit."""
        name = name.strip()
        current = self._current()
        if current is None or self._locked():
            return tr("cleanup.error.locked")
        if error := self._name_error(name):
            return error
        self._rules.save(replace(self._ordered(current), name=name, builtin=False))
        self.saved.emit()
        self.select_set(name)
        return ""

    @Slot()
    def delete_set(self) -> None:
        current = self._current()
        if current is None or current.builtin or self._locked():
            return
        self._rules.delete(current.name)
        self.saved.emit()
        self.select_set(next(iter(self._rules.book().sets), ""))

    @Slot(bool)
    def set_show_yaml(self, shown: bool) -> None:
        self._show_yaml = shown
        self._changed()

    @Slot()
    def open_folder(self) -> None:
        folder = self._rules.folder
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # The test

    @Slot(str)
    def set_source(self, source: str) -> None:
        self._source = source
        self._changed()

    @Slot(str)
    def set_sample(self, text: str) -> None:
        self._sample = text
        self._changed()

    @Slot(bool)
    def set_only_mine(self, on: bool) -> None:
        self._only_mine = on
        self._changed()

    def _test(self, current: RuleSet, rule: RuleDef | None) -> dict[str, Any]:
        available = self._loaded()
        loaded = available if self._source == "subtitle" else None
        if loaded is not None:
            cues, language, label = loaded
        else:
            blocks = [b.strip("\n") for b in self._sample.replace("\r\n", "\n").split("\n\n") if b.strip()]
            cues = [Cue(float(n), float(n) + 1, block) for n, block in enumerate(blocks)]
            first = Language.parse(rule.languages[0]) if rule is not None and rule.languages else None
            language, label = first or _ENGLISH, tr("cleanup.test.sample_name")
        test: dict[str, Any] = {
            "source": self._source,
            "can_load": available is not None,
            "sample": self._sample,
            "only_mine": self._only_mine,
            "rows": [],
            "summary": "",
            "error": "",
        }
        # Only rules that can be built are run: a draft with a broken rule shows what is wrong, not a test.
        if self._error or rule is None:
            return test
        try:
            results = clean_cues(cues, compile_sets([current], language))
        except RuleError as error:
            test["error"] = str(error)
            return test
        mine = [r for r in results if rule.name in r.rules]
        dropped = sum(r.dropped for r in mine)
        test["summary"] = tr(
            "cleanup.test.count",
            changed=tr_plural("cleanup.lines", len(mine) - dropped),
            dropped=tr_plural("cleanup.lines", dropped),
            source=label,
        )
        shown = mine if self._only_mine else results
        test["rows"] = [
            {
                "time": clock(r.cue.start),
                "before": r.cue.text.replace("\n", " ⏎ "),
                "after": (r.text or "").replace("\n", " ⏎ ") if r.changed else "",
                "state": "looped" if r.looped else "dropped" if r.dropped else "changed" if r.changed else "kept",
                "rules": ", ".join(dict.fromkeys(rule_label(n) for n in r.rules)),
                "mine": rule.name in r.rules,
            }
            for r in shown[:_SHOWN]
        ]
        return test

    # Import from Subtitle Edit

    @Slot()
    def choose_import(self) -> None:
        name, _ = QFileDialog.getOpenFileName(None, tr("cleanup.import.title"), "", tr("cleanup.import.files"))
        if name:
            self.read_import(Path(name))

    def read_import(self, path: Path) -> None:
        """Read a Subtitle Edit file and show what would be made from it; nothing is written until it is confirmed."""
        self._import_error = ""
        try:
            imported = read_file(path.read_bytes(), self._rules.book().sets, language_of(path.name))
        except (OSError, NotSubtitleEditError) as error:
            self._import, self._import_error = None, tr("cleanup.import.unreadable", file=path.name, error=str(error))
        else:
            self._import = (path.name, imported)
            if not imported.rules and not imported.skipped:
                self._import, self._import_error = None, tr("cleanup.import.nothing", file=path.name)
        self._changed()

    @Slot()
    def cancel_import(self) -> None:
        self._import, self._import_error = None, ""
        self._changed()

    @Slot()
    def confirm_import(self) -> None:
        if self._import is None or self._locked():
            return
        imported = self._import[1]
        for rule_set in imported.sets:
            self._rules.save(rule_set)
        if imported.ocr:
            book = self._rules.book()
            existing = book.sets.get(OCR_EXTRA)
            kept = existing.rules if existing is not None else ()
            taken = {r.name for r in kept}
            added = tuple(r for r in imported.ocr if r.name not in taken)
            self._rules.save(RuleSet(OCR_EXTRA, (*kept, *added)))
        self._import = None
        self.saved.emit()
        first = imported.sets[0].name if imported.sets else OCR_EXTRA
        self.select_set(first)

    # Building the view

    def _build(self) -> dict[str, Any]:
        book = self._rules.book()
        current = self._current()
        rule = self._rule_now()
        sets = [
            {
                "name": s.name,
                "label": set_label(s.name),
                "languages": set_languages(s),
                "builtin": s.builtin,
                "count": tr_plural("cleanup.rules", len(s.rules)),
                "selected": s.name == self._set,
            }
            for s in book.sets.values()
        ]
        view: dict[str, Any] = {
            "sets": sets,
            "problems": [{"file": p.file, "message": p.message} for p in book.problems],
            "locked": self._locked(),
            "folder": str(self._rules.folder),
            "preview": self._import_view(),
            "import_error": self._import_error,
            "set": {},
            "rule": {},
            "test": {},
        }
        if current is None:
            return view
        view["set"] = {
            "name": current.name,
            "label": set_label(current.name),
            "builtin": current.builtin,
            "readonly": current.builtin or self._locked(),
            "note": tr("cleanup.set.note.builtin") if current.builtin else "",
            "error": self._error,
            "yaml_shown": self._show_yaml,
            "yaml": dump_set(current) if self._show_yaml else "",
            "rules": [
                {
                    "name": r.name,
                    "label": rule_label(r.name),
                    "kind": tr(f"cleanup.kind.{r.kind.value}"),
                    "action": tr("cleanup.action.drop" if r.drops else "cleanup.action.replace"),
                    "paused": r.paused,
                    "selected": n == self._rule,
                }
                for n, r in enumerate(current.rules)
            ],
        }
        if rule is not None:
            view["rule"] = {
                "name": rule.name,
                "kind": rule.kind.value,
                "match": rule.match.value,
                "patterns": "\n".join(rule.patterns),
                "action": "drop" if rule.drops else "replace",
                "replacement": rule.replacement or "",
                "languages": ", ".join(rule.languages),
                "paused": rule.paused,
                "flags": ", ".join(rule.flags),
                "examples": [
                    {"before": e.before.strip(), "after": e.after.strip() if e.after else ""} for e in rule.examples
                ],
                "readonly": view["set"]["readonly"],
            }
            view["test"] = self._test(current, rule)
        return view

    def _import_view(self) -> dict[str, Any]:
        if self._import is None:
            return {}
        file, imported = self._import
        return {
            "file": file,
            "summary": tr(
                "cleanup.import.summary",
                sets=tr_plural("cleanup.sets", len(imported.sets)),
                rules=tr_plural("cleanup.rules", imported.rules),
            ),
            "sets": [{"name": s.name, "count": tr_plural("cleanup.rules", len(s.rules))} for s in imported.sets],
            "ocr": tr_plural("cleanup.rules", len(imported.ocr)) if imported.ocr else "",
            "skipped": [
                {"where": s.where, "text": s.text[:80], "reason": tr(f"cleanup.import.reason.{s.reason}")}
                for s in imported.skipped[:200]
            ],
            "skipped_count": len(imported.skipped),
        }
