import QtQuick
import QtQuick.Layouts
import Showrunner

// General: how Showrunner starts and the window's language. Where originals go is kept with each profile.
SettingsPage {
    id: page

    title: Strings.t("prefs.section.general")

    SettingLabel {
        text: Strings.t("prefs.general.startup")
    }

    Segmented {
        objectName: "startup"
        Layout.fillWidth: true
        name: Strings.t("prefs.general.startup")
        current: app.settings.startup
        model: [
            {"key": "last-workspace", "label": Strings.t("prefs.general.startup.last-workspace")},
            {"key": "empty", "label": Strings.t("prefs.general.startup.empty")}
        ]
        onPicked: key => app.settings.set_startup(key)
    }

    Hint {
        text: Strings.t("prefs.general.startup_hint")
    }

    SettingLabel {
        text: Strings.t("prefs.general.language")
        note: app.settings.language
    }

    Hint {
        text: Strings.t("prefs.general.language_hint")
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: Theme.space_lg
        spacing: Theme.space_md

        Hint {
            text: Strings.t("prefs.general.originals_moved")
        }

        ActionButton {
            kind: "ghost"
            iconName: "arrow"
            text: Strings.t("prefs.section.profiles")
            onClicked: page.goTo("profiles")
        }
    }
}
