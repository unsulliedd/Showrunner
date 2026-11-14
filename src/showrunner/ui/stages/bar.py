"""The right part of the toolbar: the active profile, a switch per stage, and Preview and Apply with the stamp that
says whether the preview on screen still holds."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QPushButton, QWidget

from showrunner.app.jobs.preview import FileOutcome
from showrunner.app.jobs.stages import PlanState
from showrunner.tools.dependencies.specs import SPEC_BY_ID
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.settings.page import repolish
from showrunner.ui.settings.profiles import settle_unsaved
from showrunner.ui.settings.session import ProfileSession
from showrunner.ui.stages.controller import StageController
from showrunner.ui.stages.switches import StageSwitch
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import SIZES

# The stages with an engine, in pipeline order, and the program each one needs.
STAGES = (("tracks", None), ("metadata", "mkvtoolnix"))


def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setProperty("role", "muted")
    return line


class StageBar(QWidget):
    """`open_page` asks for a Settings page; `preview_requested` and `apply_requested` for the two actions."""

    open_page = Signal(str)
    preview_requested = Signal()
    apply_requested = Signal()

    def __init__(
        self, session: ProfileSession, controller: StageController, theme: ThemeManager, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._controller = controller
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SIZES["space_md"], 0, 0, 0)
        layout.setSpacing(SIZES["space_sm"])
        profile_label = QLabel(tr("stage.profile"))
        profile_label.setProperty("role", "muted")
        layout.addWidget(profile_label)
        self.profile = QComboBox()
        self.profile.setMinimumWidth(SIZES["library_min_width"] - SIZES["space_xl"] * 4)
        self.profile.activated.connect(self._on_profile_picked)
        layout.addWidget(self.profile)
        layout.addWidget(_separator())

        self.switches: dict[str, StageSwitch] = {}
        for stage_id, _program in STAGES:
            switch = StageSwitch(stage_id, tr(f"stage.{stage_id}"), theme)
            switch.toggled.connect(lambda on, s=stage_id: session.update(s, enabled=on))
            self.switches[stage_id] = switch
            layout.addWidget(switch)
        self._build_menus()
        layout.addStretch()

        self.stamp = QLabel()
        self.stamp.setProperty("text_size", "sm")
        layout.addWidget(self.stamp)
        self.preview = QPushButton(tr("preview.button"))
        self.preview.clicked.connect(self.preview_requested)
        self.apply = QPushButton(tr("preview.apply_none"))
        self.apply.setProperty("primary", True)
        self.apply.clicked.connect(self.apply_requested)
        layout.addWidget(self.preview)
        layout.addWidget(self.apply)

        session.changed.connect(self.refresh)
        session.profiles_changed.connect(self.refresh)
        controller.changed.connect(self.refresh)
        self.refresh()

    # Menus

    def _check_action(self, menu_owner: StageSwitch, text: str, stage_id: str, option: str) -> QAction:
        action = menu_owner.menu().addAction(text)
        action.setCheckable(True)
        action.toggled.connect(lambda on: self._session.update(stage_id, **{option: on}))
        action.setData((stage_id, option))
        return action

    def _build_menus(self) -> None:
        tracks, metadata = self.switches["tracks"], self.switches["metadata"]
        self._actions = [self._check_action(tracks, tr("stage.menu.flags_from_names"), "tracks", "flags_from_names")]
        tracks.menu().addSeparator()
        tracks.menu().addAction(tr("stage.menu.track_rules")).triggered.connect(lambda: self.open_page.emit("tracks"))
        for option in ("set_title", "set_track_names", "write_implied_flags"):
            self._actions.append(self._check_action(metadata, tr(f"stage.menu.{option}"), "metadata", option))
        self.language = metadata.menu().addAction("")
        self.language.triggered.connect(self.ask_language)
        metadata.menu().addSeparator()
        naming = metadata.menu().addAction(tr("stage.menu.naming"))
        naming.triggered.connect(lambda: self.open_page.emit("naming"))

    def ask_language(self) -> None:
        current = self._session.options("metadata").untagged_language
        title, prompt = tr("stage.menu.language_title"), tr("stage.menu.language_label")
        text, ok = QInputDialog.getText(self, title, prompt, text=current)
        if ok:
            self._session.update("metadata", untagged_language=text.strip())

    # State

    def refresh(self) -> None:
        session, controller = self._session, self._controller
        self.profile.blockSignals(True)
        self.profile.clear()
        for name in session.store.names():
            shown = tr("stage.profile_changed", name=name) if name == session.name and session.is_changed else name
            self.profile.addItem(shown, name)
        self.profile.setCurrentIndex(self.profile.findData(session.name))
        self.profile.blockSignals(False)

        for action in self._actions:
            stage_id, option = action.data()
            action.blockSignals(True)
            action.setChecked(getattr(session.options(stage_id), option))
            action.blockSignals(False)
        language = session.options("metadata").untagged_language
        self.language.setText(tr("stage.menu.language", value=language or tr("stage.menu.language_none")))

        running = controller.stage_ids()
        blocks = session.blocks()
        current = controller.is_current
        preview = controller.preview
        for stage_id, program in STAGES:
            switch = self.switches[stage_id]
            switch.blockSignals(True)
            switch.setChecked(session.options(stage_id).enabled)
            switch.blockSignals(False)
            missing = (
                tr("stage.missing_program_tip", name=tr(SPEC_BY_ID[program].name_key))
                if program and stage_id not in running and controller.statuses
                else ""
            )
            block = blocks.get(stage_id)
            blocked = tr_plural("stage.blocked_tip", block.count) if block else ""
            count = None
            if preview is not None and current:
                # A file Apply writes nothing to (it needs a remux nothing can do, or nothing writes its
                # changes) is left out, as Apply leaves it out.
                count = sum(
                    1
                    for f in preview.files
                    if f.outcome in (FileOutcome.CHANGES, FileOutcome.REFUSED)
                    and (plan := f.plan_for(stage_id)) is not None
                    and plan.state is PlanState.CHANGES
                )
            switch.show_state(count=count, blocked=blocked, missing=missing)

        busy = controller.busy
        files = len(controller.to_write())
        self.preview.setEnabled(not busy)
        self.apply.setEnabled(not busy and current and files > 0)
        self.apply.setText(tr_plural("preview.apply", files) if current and files else tr("preview.apply_none"))
        self.apply.setToolTip("" if current or preview is None else tr("preview.apply_tip_stale"))
        if preview is None:
            self.stamp.setText("")
        elif current:
            time = controller.preview_time.strftime("%H:%M") if controller.preview_time else ""
            self.stamp.setText(tr_plural("preview.stamp", len(preview.files), time=time))
        else:
            self.stamp.setText(tr("preview.out_of_date"))
        self.stamp.setProperty("role", "muted" if current else "notice")
        repolish(self.stamp)

    def _on_profile_picked(self, index: int) -> None:
        name = self.profile.itemData(index)
        if name == self._session.name:
            return
        if settle_unsaved(self, self._session):
            self._session.switch(name)
        self.refresh()
