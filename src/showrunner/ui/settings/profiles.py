"""The Profiles page: the saved profiles and the built-in one, with the actions on their files. Each action acts at
once; only the edits of the active profile wait for Save."""

from __future__ import annotations

import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from showrunner.app.profiles.errors import ProfileError
from showrunner.app.profiles.profile import Profile
from showrunner.core.options.registry import REGISTRY
from showrunner.core.options.serialization import to_sparse
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.settings.page import SettingsPage, clear_layout, heading, label, link_button, repolish
from showrunner.ui.settings.session import ProfileSession
from showrunner.ui.theme.tokens import SIZES

NAME_ROLE = Qt.ItemDataRole.UserRole + 1
_FILE_FILTER = "*.json"


def ask_unsaved(parent: QWidget, name: str) -> QMessageBox.StandardButton:
    """Save, Discard or Cancel for unsaved edits of the active profile."""
    buttons = QMessageBox.StandardButton
    return QMessageBox.question(
        parent,
        tr("settings.unsaved.title"),
        tr("settings.unsaved.text", name=name),
        buttons.Save | buttons.Discard | buttons.Cancel,
        buttons.Save,
    )


def settle_unsaved(parent: QWidget, session: ProfileSession) -> bool:
    """Ask what to do with unsaved edits before they would be lost; False when the user cancels."""
    if not session.is_changed:
        return True
    answer = ask_unsaved(parent, session.name)
    if answer == QMessageBox.StandardButton.Discard:
        return True
    if answer != QMessageBox.StandardButton.Save:
        return False
    if session.read_only:
        name, ok = QInputDialog.getText(parent, tr("settings.save_as_title"), tr("settings.save_as_label"))
        if not ok or not name.strip():
            return False
        try:
            session.save_as(name.strip())
        except (ProfileError, OSError) as error:
            QMessageBox.warning(parent, tr("settings.save_as_title"), str(error))
            return False
        return True
    try:
        session.save()
    except (ProfileError, OSError) as error:
        QMessageBox.warning(parent, tr("settings.save"), str(error))
        return False
    return True


def differences(profile: Profile) -> list[tuple[str, str]]:
    """One line per stage: what its options change from the defaults."""
    lines = []
    for stage_id in REGISTRY.ids():
        options = profile.for_stage(stage_id)
        sparse = to_sparse(options)
        name = tr(f"stage.{stage_id}")
        if not sparse:
            lines.append((name, tr("settings.profiles.same")))
            continue
        if stage_id == "tracks":
            on = sum(rule.enabled for rule in options.rules)
            detail = tr_plural("settings.profiles.rules", len(options.rules), on=on)
        else:
            detail = tr_plural("settings.profiles.changed", len(sparse))
        lines.append((name, detail))
    return lines


class ProfilesPage(SettingsPage):
    def __init__(self, session: ProfileSession, parent: QWidget | None = None) -> None:
        super().__init__(tr("settings.page.profiles"), tr("settings.profiles.lead"), parent=parent)
        self._session = session
        columns = QHBoxLayout()
        columns.setSpacing(SIZES["space_xl"])

        left = QVBoxLayout()
        left.setSpacing(SIZES["space_md"])
        self.list = QListWidget()
        self.list.setProperty("role", "profiles")
        self.list.currentItemChanged.connect(lambda *_: self._show_selected())
        left.addWidget(self.list, 1)
        first = QHBoxLayout()
        second = QHBoxLayout()
        self.duplicate = QPushButton(tr("settings.profiles.duplicate"))
        self.duplicate.clicked.connect(self._duplicate)
        self.rename = QPushButton(tr("settings.profiles.rename"))
        self.rename.clicked.connect(self._rename)
        self.delete = link_button(tr("settings.profiles.delete"), self._delete)
        self.delete.setProperty("danger", True)
        self.import_button = QPushButton(tr("settings.profiles.import"))
        self.import_button.clicked.connect(self._import)
        self.export = QPushButton(tr("settings.profiles.export"))
        self.export.clicked.connect(self._export)
        for row, buttons in (
            (first, (self.duplicate, self.rename, self.delete)),
            (second, (self.import_button, self.export)),
        ):
            row.setSpacing(SIZES["space_md"])
            for button in buttons:
                row.addWidget(button)
            row.addStretch()
            left.addLayout(row)
        left.addWidget(label(tr("settings.profiles.default_note"), "muted", wrap=True, size="sm"))
        columns.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(SIZES["space_md"])
        top = QHBoxLayout()
        self.name = heading("")
        self.name.setProperty("text_size", "lg")
        self.use = QPushButton(tr("settings.profiles.use"))
        self.use.clicked.connect(self._use)
        top.addWidget(self.name, 1)
        top.addWidget(self.use)
        right.addLayout(top)
        right.addWidget(label(tr("settings.profiles.active_note"), "muted", wrap=True, size="sm"))
        right.addWidget(heading(tr("settings.profiles.differs")))
        self.differs = QGridLayout()
        self.differs.setHorizontalSpacing(SIZES["space_xl"])
        right.addLayout(self.differs)
        right.addWidget(heading(tr("settings.profiles.file")))
        self.file = QGridLayout()
        self.file.setHorizontalSpacing(SIZES["space_xl"])
        right.addLayout(self.file)
        right.addStretch()
        columns.addLayout(right, 1)
        self.body.addLayout(columns, 1)

        session.changed.connect(self.refresh)
        session.profiles_changed.connect(self.refresh)
        self.refresh()

    # The list

    def selected(self) -> str:
        item = self.list.currentItem()
        return item.data(NAME_ROLE) if item is not None else self._session.name

    def refresh(self, select: str | None = None) -> None:
        select = select or (self.selected() if self.list.count() else self._session.name)
        store = self._session.store
        self.list.blockSignals(True)
        self.list.clear()
        for name in store.names():
            tags = []
            if store.is_builtin(name):
                tags.append(tr("settings.profiles.built_in"))
            if name == self._session.name:
                tags.append(tr("settings.profiles.active"))
            text = name if not tags else f"{name}    {' · '.join(tags)}"
            item = QListWidgetItem(text)
            item.setData(NAME_ROLE, name)
            self.list.addItem(item)
            if name.casefold() == select.casefold():
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self._show_selected()

    def _show_selected(self) -> None:
        name = self.selected()
        store = self._session.store
        active = name == self._session.name
        builtin = store.is_builtin(name)
        self.name.setText(name)
        self.use.setText(tr("settings.profiles.active" if active else "settings.profiles.use"))
        self.use.setEnabled(not active)
        self.use.setProperty("primary", not active)
        repolish(self.use)
        self.rename.setEnabled(not builtin)
        self.delete.setEnabled(not builtin)
        try:
            profile = self._session.profile if active else store.load(name).value
        except (ProfileError, OSError):
            profile = None
        clear_layout(self.differs)
        for row, (stage, text) in enumerate(differences(profile) if profile else []):
            self.differs.addWidget(label(stage, "muted"), row, 0, Qt.AlignmentFlag.AlignTop)
            self.differs.addWidget(label(text, wrap=True), row, 1)
        self.differs.setColumnStretch(1, 1)
        clear_layout(self.file)
        path = store.file_path(name)
        if path is None:
            self.file.addWidget(label(tr("settings.profiles.no_file"), "muted", wrap=True), 0, 0, 1, 2)
            return
        saved = (
            datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            if path.is_file()
            else tr("common.none")
        )
        for row, (key, value) in enumerate((("name", path.name), ("saved", saved))):
            self.file.addWidget(label(tr(f"settings.profiles.file_{key}"), "muted"), row, 0)
            self.file.addWidget(label(value), row, 1)
        self.file.setColumnStretch(1, 1)

    # Prompts, replaced in tests

    def ask_text(self, title: str, text: str, value: str = "") -> str:
        answer, ok = QInputDialog.getText(self, title, text, text=value)
        return answer.strip() if ok else ""

    def confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    def ask_open(self) -> Path | None:
        name, _ = QFileDialog.getOpenFileName(self, tr("settings.profiles.import"), "", _FILE_FILTER)
        return Path(name) if name else None

    def ask_save(self, suggested: str) -> Path | None:
        name, _ = QFileDialog.getSaveFileName(self, tr("settings.profiles.export"), suggested, _FILE_FILTER)
        return Path(name) if name else None

    def _fail(self, error: Exception) -> None:
        QMessageBox.warning(self, tr("settings.page.profiles"), tr("settings.profiles.failed", error=error))

    # Actions

    def _use(self) -> None:
        name = self.selected()
        if settle_unsaved(self, self._session):
            self._session.switch(name)

    def _duplicate(self) -> None:
        name = self.selected()
        new = self.ask_text(
            tr("settings.profiles.duplicate"), tr("settings.save_as_label"), tr("settings.profiles.copy_of", name=name)
        )
        if not new:
            return
        try:
            self._session.store.duplicate(name, new)
        except (ProfileError, OSError) as error:
            self._fail(error)
            return
        self._session.profiles_changed.emit()
        self.refresh(new)

    def _rename(self) -> None:
        name = self.selected()
        new = self.ask_text(tr("settings.profiles.rename"), tr("settings.save_as_label"), name)
        if not new or new == name:
            return
        try:
            self._session.store.rename(name, new)
        except (ProfileError, OSError) as error:
            self._fail(error)
            return
        self._session.renamed(name, new)
        self.refresh(new)

    def _delete(self) -> None:
        name = self.selected()
        if not self.confirm(tr("settings.profiles.delete"), tr("settings.profiles.delete_confirm", name=name)):
            return
        if name == self._session.name:
            self._session.switch(self._session.store.names()[0])
        try:
            self._session.store.delete(name)
        except (ProfileError, OSError) as error:
            self._fail(error)
            return
        self._session.profiles_changed.emit()
        self.refresh(self._session.name)

    def _import(self) -> None:
        if (source := self.ask_open()) is None:
            return
        try:
            loaded = self._session.store.import_file(source)
        except (ProfileError, OSError) as error:
            self._fail(error)
            return
        self._session.profiles_changed.emit()
        self.refresh(loaded.value.name)

    def _export(self) -> None:
        name = self.selected()
        if (destination := self.ask_save(f"{name}.json")) is None:
            return
        try:
            self._session.store.export(name, destination)
        except (ProfileError, OSError) as error:
            self._fail(error)
