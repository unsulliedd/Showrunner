import QtQuick
import QtQuick.Layouts
import Showrunner

// About: the version, the links once the project has a public address, and the licences of what ships with it.
SettingsPage {
    title: Strings.t("prefs.about.title")
    lead: Strings.t("prefs.about.lead")

    UiText {
        Layout.fillWidth: true
        text: Strings.t("app.name") + "  " + Strings.f("prefs.version", {"version": app.settings.version})
        font.weight: Font.DemiBold
    }

    SettingLabel {
        text: Strings.t("prefs.about.links")
    }

    Flow {
        Layout.fillWidth: true
        spacing: Theme.space_sm

        Repeater {
            model: app.settings.links

            delegate: ActionButton {
                required property var modelData

                kind: "outline"
                iconName: "link"
                text: modelData.label
                // No public address is declared yet; the reason is said under the buttons.
                enabled: false
            }
        }
    }

    Hint {
        text: Strings.t("prefs.about.no_address")
    }

    SettingLabel {
        text: Strings.t("prefs.about.licenses")
    }

    Repeater {
        model: app.settings.licenses

        delegate: RowLayout {
            id: part

            required property var modelData

            Layout.fillWidth: true
            Layout.preferredHeight: Theme.row_md
            spacing: Theme.space_lg

            UiText {
                Layout.preferredWidth: Theme.menu_width
                text: part.modelData.name
                font.weight: Font.Medium
            }

            UiText {
                Layout.fillWidth: true
                text: part.modelData.license
                color: Theme.muted
            }

            ActionButton {
                visible: part.modelData.path !== ""
                kind: "ghost"
                text: Strings.t("prefs.about.open")
                onClicked: app.settings.open_license(part.modelData.path)
            }
        }
    }
}
