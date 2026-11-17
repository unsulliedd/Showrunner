import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A plain text field on the well colour; `mono` for names, patterns and templates. `label` names it for screen
// readers. `invalid` draws the border as a problem.
TextField {
    id: field

    property bool mono: false
    property string label: ""
    property bool invalid: false

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
        border.color: field.invalid ? Theme.drop : field.activeFocus ? Theme.control : Theme.line
    }
}
