"""The Settings dialog's Python side: General, Profiles, AI models, Shortcuts and About, with Programs and Appearance
beside it.

Everything here applies at once and is saved at once; the dialog has no Save button. Profiles are edited as files:
a change reaches the batches that follow the profile through `Batches`, so their plans and the pill follow.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import QFileDialog

from showrunner import __version__
from showrunner.app.ai import AI
from showrunner.app.profiles.errors import ProfileError, ProfileExistsError
from showrunner.app.settings.app_settings import Startup, load_settings, save_settings
from showrunner.stages.mux.options import MuxOptions, Original, check_names
from showrunner.stages.subtitles.options import SubtitlesOptions, bad_new_file_text
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.quick.look import Look
from showrunner.ui.quick.programs import Programs
from showrunner.ui.quick.review import backend_name

if TYPE_CHECKING:
    from showrunner.ui.quick.window import WindowController

_log = logging.getLogger(__name__)

# The dialog's sections in their order, each with its icon.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("general", "sliders"),
    ("profiles", "list"),
    ("programs", "terminal"),
    ("ai", "subs"),
    ("appearance", "image"),
    ("shortcuts", "brace"),
    ("about", "sparkle"),
)
# Key sequences the window binds; QML reads them from here, so the Shortcuts section cannot disagree.
SHORTCUTS: dict[str, str] = {"palette": "Ctrl+K", "settings": "Ctrl+,"}
# The Shortcuts section: the keys, then what they do. Keys inside a place are listed where they work.
SHORTCUT_LIST: tuple[tuple[tuple[str, ...], str], ...] = (
    ((SHORTCUTS["palette"],), "palette"),
    ((SHORTCUTS["settings"],), "settings"),
    (("Esc",), "close"),
    (("Up", "Down", "Home", "End"), "sections"),
    (("Up", "Down", "Return"), "results"),
    (("Menu", "Shift+F10"), "place_menu"),
    (("Return",), "add_token"),
    (("Del",), "remove_chip"),
    (("Ctrl+Left", "Ctrl+Right"), "move_chip"),
    (("Ctrl+Left", "Ctrl+Right"), "move_column"),
    (("Ctrl+Up", "Ctrl+Down"), "move_card"),
    (("Ctrl+Return",), "save_rule"),
)
FONTS_DIR = Path(__file__).parent / "fonts"
# Licences of what ships with the app; a bundled licence text can be opened.
LICENSES: tuple[tuple[str, str, Path | None], ...] = (
    ("showrunner", "gpl3", None),
    ("inter", "ofl", FONTS_DIR / "inter" / "OFL.txt"),
    ("jetbrains_mono", "ofl", FONTS_DIR / "jetbrains-mono" / "OFL.txt"),
    ("qt", "lgpl3", None),
)
REPOSITORY = "https://github.com/unsulliedd/Showrunner"
# The links About offers, by the key of their label. `open_link` opens only these.
LINKS: dict[str, str] = {
    "release_notes": f"{REPOSITORY}/releases",
    "source": REPOSITORY,
    "report": f"{REPOSITORY}/issues",
}


def mux_problems(options: MuxOptions) -> dict[str, str]:
    """The keep folder or suffix that cannot be part of a file name, worded, by field."""
    return {name.value: tr(f"review.blocked.{name.value}", folder=options.keep_folder) for name in check_names(options)}


def key_text(sequence: str) -> str:
    """A key sequence as the platform writes it ("Ctrl+K")."""
    return QKeySequence(sequence).toString(QKeySequence.SequenceFormat.NativeText)


class Settings(QObject):
    """`app.settings`. `open_asked` asks the window to open the dialog on a section."""

    changed = Signal()
    open_asked = Signal(str)

    def __init__(self, window: WindowController) -> None:
        super().__init__(window)
        self._window = window
        self.look = Look(parent=self)
        self.programs_view = Programs(parent=self)
        self._picked = ""
        self._message = ""
        self._tone = "add"
        window.batch_changed.connect(self.changed)
        window.jobs.started.connect(self.changed)
        window.jobs.ended.connect(self.changed)
        window.found.ai_changed.connect(self.changed)

    # The dialog

    @Property(list, constant=True)
    def sections(self) -> list[dict[str, str]]:
        return [{"key": key, "icon": icon, "label": tr(f"prefs.section.{key}")} for key, icon in SECTIONS]

    @Property(str, constant=True)
    def version(self) -> str:
        return __version__

    @Property(QObject, constant=True)
    def appearance(self) -> Look:
        return self.look

    @Property(QObject, constant=True)
    def programs(self) -> Programs:
        return self.programs_view

    @Property("QVariantMap", constant=True)
    def keys(self) -> dict[str, str]:
        """The window's key sequences, for QML's `Shortcut` items."""
        return dict(SHORTCUTS)

    @Slot(str)
    def open(self, section: str = "general") -> None:
        if section == "profiles":
            self._picked = ""  # the selected batch's profile, as the pill shows it
        self._message = ""
        self.changed.emit()
        self.open_asked.emit(section)

    @Slot(str)
    def opened(self, section: str) -> None:
        """The dialog shows `section`; Programs checks its programs the first time it is shown."""
        if section == "programs":
            self.programs_view.show(self.programs_view.focus)
        elif section == "ai":
            self.check_ai()

    def get_program(self, spec_id: str) -> None:
        """A "Get it" somewhere in the window: open Programs on that program's row."""
        self.programs_view.show(spec_id)
        self.open("programs")

    @Slot()
    def closed(self) -> None:
        self.programs_view.stop()

    # General

    @Property(str, notify=changed)
    def startup(self) -> str:
        return load_settings().value.startup.value

    @Slot(str)
    def set_startup(self, startup: str) -> None:
        if startup in set(Startup):
            self._remember(startup=Startup(startup))

    @Property(str, constant=True)
    def language(self) -> str:
        return tr(f"prefs.language.{load_settings().value.ui_language}")

    # AI models

    @Property("QVariantMap", notify=changed)
    def ai(self) -> dict[str, Any]:
        """The backend and whether it answers, the model chosen, and the installed ones to choose from."""
        status = AI.status()
        backend = backend_name()
        running = status is not None and status.running
        installed = list(status.models) if status is not None else []
        chosen = load_settings().value.ai_model
        if status is None:
            state = tr("prefs.ai.state.checking", backend=backend)
        elif running:
            state = tr_plural("prefs.ai.state.running", len(installed), backend=backend)
        else:
            state = tr("prefs.ai.state.stopped", backend=backend)
        if not chosen:
            model = tr("prefs.ai.model.none")
        elif running and chosen not in installed:
            model = tr("prefs.ai.model.not_installed", model=chosen)
        else:
            model = chosen
        return {
            "backend": backend,
            "state": state,
            "model": model,
            "models": [{"key": name, "text": name, "enabled": True} for name in installed],
            "empty": tr("prefs.ai.model.empty", backend=backend) if running and not installed else "",
        }

    @Slot(str)
    def set_ai_model(self, name: str) -> None:
        """The model for every place that chooses none; the plans follow it."""
        self._remember(ai_model=name)
        self._window.workspace.replan()

    @Slot()
    def check_ai(self) -> None:
        self._window.found.check_ai(now=True)

    # Profiles

    @property
    def _store(self) -> Any:
        return self._window.store

    @Property(bool, notify=changed)
    def profiles_locked(self) -> bool:
        """Profile files wait while files are being applied: a batch being applied follows one of them."""
        return self._window.jobs.busy or self._window.applying

    @Property(str, notify=changed)
    def picked(self) -> str:
        names = self._store.names()
        if self._picked in names:
            return self._picked
        return self._window.profile if self._window.profile in names else names[0]

    @Slot(str)
    def pick(self, name: str) -> None:
        if name in self._store.names() and name != self.picked:
            self._picked = name
            self._message = ""
            self.changed.emit()

    @Property(list, notify=changed)
    def profiles(self) -> list[dict[str, Any]]:
        used = self._window.profile if self._window.has_batch else ""
        return [
            {"name": name, "builtin": self._store.is_builtin(name), "used": name == used}
            for name in self._store.names()
        ]

    @Property("QVariantMap", notify=changed)
    def profile(self) -> dict[str, Any]:
        """The picked profile as saved: what Settings edits in it, and what is wrong with it."""
        name = self.picked
        try:
            saved = self._store.load(name).value
        except (ProfileError, OSError):
            _log.exception("Could not read the profile %s", name)
            return {"name": name, "readable": False}
        mux: MuxOptions = saved.for_stage("mux")
        subtitles: SubtitlesOptions = saved.for_stage("subtitles")
        problems = mux_problems(mux)
        if bad_new_file_text(subtitles.new_file_text):
            problems["new_file_text"] = tr("review.blocked.new_file_text")
        return {
            "name": name,
            "readable": True,
            "builtin": self._store.is_builtin(name),
            "editable": not self._store.is_builtin(name) and not self.profiles_locked,
            "flags_from_names": saved.for_stage("tracks").flags_from_names,
            "original": mux.original.value,
            "keep_folder": mux.keep_folder,
            "suffix": mux.suffix,
            "new_file_text": subtitles.new_file_text,
            "problems": problems,
            "batches": len(self._window.batches.following(name)),
        }

    @Property(str, notify=changed)
    def message(self) -> str:
        return self._message

    @Property(str, notify=changed)
    def message_tone(self) -> str:
        """ "add" for what was done, "drop" for what could not be."""
        return self._tone

    @Slot(bool)
    def set_flags_from_names(self, on: bool) -> None:
        self._edit("tracks", flags_from_names=on)

    @Slot(str)
    def set_original(self, original: str) -> None:
        if original in set(Original):
            self._edit("mux", original=Original(original))

    @Slot(str)
    def set_keep_folder(self, folder: str) -> None:
        self._edit("mux", keep_folder=folder.strip())

    @Slot(str)
    def set_suffix(self, suffix: str) -> None:
        self._edit("mux", suffix=suffix)

    @Slot(str)
    def set_new_file_text(self, text: str) -> None:
        """Kept as typed: one that cannot name a file shows its problem here and blocks the subtitle plans that would
        use it, as a bad suffix does."""
        self._edit("subtitles", new_file_text=text)

    @Slot(str, result=str)
    def rename(self, new_name: str) -> str:
        """Rename the picked profile; returns why not, or "" when renamed."""
        old, new = self.picked, new_name.strip()
        problem = self._file_action(lambda: self._window.batches.rename_profile(old, new), new)
        if not problem:
            self._picked = new
            self._done(tr("prefs.profiles.renamed", old=old, name=new))
        return problem

    @Slot(str, result=str)
    def duplicate(self, new_name: str) -> str:
        new = new_name.strip()
        problem = self._file_action(lambda: self._store.duplicate(self.picked, new), new)
        if not problem:
            self._picked = new
            self._done(tr("prefs.profiles.duplicated", name=new))
        return problem

    @Slot()
    def delete(self) -> None:
        """The dialog asked first. Batches that followed it keep their choices over the default profile."""
        name = self.picked
        if problem := self._file_action(lambda: self._window.batches.delete_profile(name), name):
            self._say(problem)
            return
        self._picked = ""
        self._done(tr("prefs.profiles.deleted", name=name))

    @Slot()
    def import_profile(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(None, tr("prefs.profiles.import"), "", tr("prefs.profiles.filter"))
        if chosen:
            self.import_from(Path(chosen))

    def import_from(self, path: Path) -> None:
        try:
            loaded = self._store.import_file(path)
        except ProfileExistsError:
            self._say(tr("profile.error.exists", name=path.stem))
            return
        except (ProfileError, OSError):
            self._say(tr("prefs.profiles.import_failed", file=path.name))
            return
        self._picked = loaded.value.name
        self._done(tr("prefs.profiles.imported", name=loaded.value.name))

    @Slot()
    def export_profile(self) -> None:
        name = self.picked
        chosen, _ = QFileDialog.getSaveFileName(
            None, tr("prefs.profiles.export"), f"{name}.json", tr("prefs.profiles.filter")
        )
        if chosen:
            self.export_to(Path(chosen))

    def export_to(self, path: Path) -> None:
        try:
            self._store.export(self.picked, path)
        except (ProfileError, OSError) as error:
            self._say(tr("prefs.profiles.export_failed", error=error))
            return
        self._say(tr("prefs.profiles.exported", file=path.name), "add")

    # Shortcuts and About

    @Property(list, constant=True)
    def shortcuts(self) -> list[dict[str, Any]]:
        return [
            {"keys": [key_text(k) for k in keys], "text": tr(f"prefs.shortcuts.{what}")} for keys, what in SHORTCUT_LIST
        ]

    @Property(list, constant=True)
    def licenses(self) -> list[dict[str, str]]:
        return [
            {
                "name": tr(f"prefs.about.part.{part}"),
                "license": tr(f"prefs.about.license.{license}"),
                "path": str(path) if path is not None else "",
            }
            for part, license, path in LICENSES
        ]

    @Property(list, constant=True)
    def links(self) -> list[dict[str, str]]:
        return [{"key": key, "label": tr(f"prefs.about.link.{key}"), "url": url} for key, url in LINKS.items()]

    @Slot(str)
    def open_link(self, url: str) -> None:
        if url in LINKS.values():
            QDesktopServices.openUrl(QUrl(url))

    @Slot(str)
    def open_license(self, path: str) -> None:
        if any(str(file) == path for _part, _license, file in LICENSES if file is not None):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # Inside

    def _edit(self, stage_id: str, **changes: Any) -> None:
        if not self.profile.get("editable"):
            return
        try:
            self._window.batches.edit_profile(self.picked, stage_id, **changes)
        except (ProfileError, OSError) as error:
            self._say(tr("prefs.profiles.failed", error=error))
            return
        self._window.profiles_edited()

    def _file_action(self, action: Any, name: str) -> str:
        """Run a change of profile files; returns why it was refused, worded, or "" when done."""
        if self.profiles_locked:
            return tr("prefs.profiles.locked")
        try:
            action()
        except ProfileExistsError:
            return tr("profile.error.exists", name=name)
        except ProfileError:
            return tr("profile.error.name")
        except OSError as error:
            _log.exception("Could not change the profile files")
            return tr("prefs.profiles.failed", error=error)
        return ""

    def _done(self, text: str) -> None:
        self._message, self._tone = text, "add"
        self._window.profiles_edited()
        self.changed.emit()

    def _say(self, text: str, tone: str = "drop") -> None:
        self._message, self._tone = text, tone
        self.changed.emit()

    def _remember(self, **changes: Any) -> None:
        try:
            save_settings(replace(load_settings().value, **changes))
        except OSError:
            _log.exception("Could not save the settings")
        self.changed.emit()
