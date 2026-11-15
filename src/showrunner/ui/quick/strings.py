"""The `Strings` object: QML gets every piece of UI text from the string catalog through it."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Slot

from showrunner.ui.i18n.catalog import tr, tr_plural


class Strings(QObject):
    """`Strings.t("home.title")`, `Strings.f("top.changes", {"files": 3})` with `{name}` placeholders, and
    `Strings.n("time.days", 3)` for a `.one` / `.other` pair."""

    @Slot(str, result=str)
    def t(self, key: str) -> str:
        return tr(key)

    @Slot(str, "QVariantMap", result=str)
    def f(self, key: str, values: dict[str, Any]) -> str:
        return tr(key, **values)

    @Slot(str, int, result=str)
    def n(self, key: str, count: int) -> str:
        return tr_plural(key, count)
