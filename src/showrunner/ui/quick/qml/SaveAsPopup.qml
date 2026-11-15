import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// Asks for a profile's name and hands it to `submit`, which returns why it was refused or "" when done. By default
// it saves the batch's choices as a new profile; Settings uses it to rename and duplicate.
Popup {
    id: popup

    property string problem: ""
    property string heading: Strings.t("profile.save_as_title")
    property string action: Strings.t("profile.save")
    property string initial: ""
    property var submit: name => app.save_profile_as(name)

    modal: true
    focus: true
    padding: Theme.space_xl
    anchors.centerIn: Overlay.overlay
    onOpened: {
        problem = ""
        field.text = initial
        field.selectAll()
        field.forceActiveFocus()
    }

    function save() {
        problem = submit(field.text)
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
            text: popup.heading
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
                text: popup.action
                enabled: field.text.trim() !== ""
                onClicked: popup.save()
            }
        }
    }
}
