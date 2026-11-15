import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A plain text field on the well colour; `mono` for names, patterns and templates. `label` names it for screen
// readers.
TextField {
    id: field

    property bool mono: false
    property string label: ""

    implicitHeight: Theme.row_md
    leftPadding: Theme.space_md
    rightPadding: Theme.space_md
    color: Theme.ink
    placeholderTextColor: Theme.faint
    selectionColor: Theme.select
    selectedTextColor: Theme.ink
    font.family: mono ? Theme.mono : Theme.font
    font.pixelSize: mono ? Theme.text_sm : Theme.text_md
    verticalAlignment: TextInput.AlignVCenter
    Accessible.name: label

    background: Rectangle {
        radius: Theme.radius_md
        color: Theme.well
        border.width: Theme.stroke
        border.color: field.activeFocus ? Theme.control : Theme.line
    }
}
