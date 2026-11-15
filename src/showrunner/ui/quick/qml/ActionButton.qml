import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A button: "primary" fills with the control color, "outline" sits on a raised fill with a border, "ghost" has
// neither until the pointer is over it. A checkable one shows its on state with the control colour on its border.
AbstractButton {
    id: control

    property string kind: "outline"
    property string iconName: ""
    property int size: Theme.row_md
    readonly property color ink: !enabled ? Theme.faint : kind === "primary" ? Theme.control_ink : Theme.ink

    implicitHeight: size
    implicitWidth: content.implicitWidth + 2 * Theme.space_lg
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: checkable ? Accessible.CheckBox : Accessible.Button
    Accessible.checked: checked
    Accessible.name: text

    background: Rectangle {
        radius: Theme.radius_md
        color: control.kind === "primary" ? (control.enabled ? Theme.control : Theme.panel_3)
             : control.hovered && control.enabled ? Theme.panel_3
             : control.kind === "outline" ? Theme.panel_2 : "transparent"
        border.width: control.kind === "outline" || control.visualFocus ? Theme.stroke : 0
        border.color: control.visualFocus || control.checked ? Theme.control : Theme.line_strong
    }

    contentItem: Item {
        implicitWidth: content.implicitWidth
        implicitHeight: content.implicitHeight

        Row {
            id: content

            anchors.centerIn: parent
            spacing: Theme.space_md

            Icon {
                anchors.verticalCenter: parent.verticalCenter
                visible: control.iconName !== ""
                name: control.iconName
                color: control.ink
            }

            UiText {
                anchors.verticalCenter: parent.verticalCenter
                text: control.text
                color: control.ink
                font.weight: control.kind === "primary" ? Font.Medium : Font.Normal
            }
        }
    }
}
