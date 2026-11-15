import QtQuick
import QtQuick.Layouts
import Showrunner

// Shortcuts: the keys of the window and of each place, as the platform writes them.
SettingsPage {
    title: Strings.t("prefs.shortcuts.title")
    lead: Strings.t("prefs.shortcuts.lead")

    Repeater {
        model: app.settings.shortcuts

        delegate: RowLayout {
            id: shortcut

            required property var modelData

            Layout.fillWidth: true
            Layout.preferredHeight: Theme.row_md
            spacing: Theme.space_lg

            UiText {
                Layout.fillWidth: true
                text: shortcut.modelData.text
            }

            Repeater {
                model: shortcut.modelData.keys

                delegate: Rectangle {
                    required property string modelData

                    implicitWidth: key.implicitWidth + 2 * Theme.space_md
                    implicitHeight: Theme.row_sm
                    radius: Theme.radius_sm
                    color: Theme.panel_2
                    border.width: Theme.stroke
                    border.color: Theme.line_strong

                    UiText {
                        id: key

                        anchors.centerIn: parent
                        mono: true
                        text: parent.modelData
                        color: Theme.muted
                        font.pixelSize: Theme.text_xs
                    }
                }
            }
        }
    }
}
