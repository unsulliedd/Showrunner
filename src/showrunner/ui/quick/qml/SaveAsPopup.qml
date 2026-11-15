import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// Asks for a new profile's name and saves the batch's choices under it; the reason shows when a name is refused.
Popup {
    id: popup

    property string problem: ""

    modal: true
    focus: true
    padding: Theme.space_xl
    anchors.centerIn: Overlay.overlay
    onOpened: {
        problem = ""
        field.text = ""
        field.forceActiveFocus()
    }

    function save() {
        problem = app.save_profile_as(field.text)
        if (problem === "")
            close()
    }

    background: Rectangle {
        implicitWidth: Theme.menu_width * 2
        radius: Theme.radius_lg
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: Theme.line_strong
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.space_lg

        UiText {
            text: Strings.t("profile.save_as_title")
            font.weight: Font.DemiBold
        }

        TextField {
            id: field

            Layout.fillWidth: true
            placeholderText: Strings.t("profile.name")
            placeholderTextColor: Theme.faint
            color: Theme.ink
            font.family: Theme.font
            font.pixelSize: Theme.text_md
            Accessible.name: Strings.t("profile.name")
            onAccepted: popup.save()

            background: Rectangle {
                implicitHeight: Theme.row_md
                radius: Theme.radius_md
                color: Theme.well
                border.width: Theme.stroke
                border.color: field.activeFocus ? Theme.control : Theme.line_strong
            }
        }

        UiText {
            Layout.fillWidth: true
            visible: popup.problem !== ""
            text: popup.problem
            color: Theme.drop
            wrapMode: Text.WordWrap
            font.pixelSize: Theme.text_sm
        }

        RowLayout {
            Layout.alignment: Qt.AlignRight
            spacing: Theme.space_md

            ActionButton {
                kind: "ghost"
                text: Strings.t("common.cancel")
                onClicked: popup.close()
            }

            ActionButton {
                kind: "primary"
                text: Strings.t("profile.save")
                enabled: field.text.trim() !== ""
                onClicked: popup.save()
            }
        }
    }
}
