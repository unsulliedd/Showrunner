import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A text field with a search icon and an italic placeholder; `hint` shows a key chip at the right end.
TextField {
    id: field

    property string hint: ""

    implicitHeight: Theme.row_md
    leftPadding: Theme.space_md + Theme.icon_md + Theme.space_md
    rightPadding: hint !== "" ? chip.width + 2 * Theme.space_md : Theme.space_md
    color: Theme.ink
    placeholderTextColor: Theme.faint
    selectionColor: Theme.select
    selectedTextColor: Theme.ink
    font.family: Theme.font
    font.pixelSize: Theme.text_md
    font.italic: text === ""
    verticalAlignment: TextInput.AlignVCenter
    Accessible.name: placeholderText

    background: Rectangle {
        radius: Theme.radius_md
        color: Theme.well
        border.width: Theme.stroke
        border.color: field.activeFocus ? Theme.control : Theme.line

        Icon {
            anchors.left: parent.left
            anchors.leftMargin: Theme.space_md
            anchors.verticalCenter: parent.verticalCenter
            name: "search"
            size: Theme.icon_md
        }

        Rectangle {
            id: chip

            visible: field.hint !== ""
            anchors.right: parent.right
            anchors.rightMargin: Theme.space_sm + Theme.space_xs
            anchors.verticalCenter: parent.verticalCenter
            width: chipText.implicitWidth + 2 * Theme.space_sm + Theme.space_xs
            height: Theme.row_sm - Theme.space_sm
            radius: Theme.radius_sm
            color: Theme.panel_2
            border.width: Theme.stroke
            border.color: Theme.line_strong

            UiText {
                id: chipText

                anchors.centerIn: parent
                mono: true
                text: field.hint
                color: Theme.muted
                font.pixelSize: Theme.text_xs
            }
        }
    }
}
