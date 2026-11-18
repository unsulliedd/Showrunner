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
    // From the label's own width, so a button given less room elides its label without a binding loop.
    implicitWidth: label.implicitWidth + (glyph.visible ? glyph.width + content.spacing : 0) + 2 * Theme.space_lg
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: checkable ? Accessible.CheckBox : Accessible.Button
    Accessible.checked: checked
    Accessible.name: text

    background: Rectangle {
        radius: Theme.radius_md
        color: control.kind === "primary" ? (control.enabled ? Theme.control : Theme.panel_3)
             : control.down && control.enabled ? Theme.line
             : control.hovered && control.enabled ? Theme.panel_3
             : control.kind === "outline" ? Theme.panel_2 : "transparent"
        border.width: control.kind === "outline" || control.visualFocus ? Theme.stroke : 0
        border.color: control.visualFocus || control.checked ? Theme.control : Theme.line_strong
    }

    contentItem: Item {
        implicitHeight: content.implicitHeight

        Row {
            id: content

            anchors.centerIn: parent
            spacing: Theme.space_md

            Icon {
                id: glyph

                anchors.verticalCenter: parent.verticalCenter
                visible: control.iconName !== ""
                name: control.iconName
                color: control.ink
            }

            UiText {
                id: label

                anchors.verticalCenter: parent.verticalCenter
                // The label gives up what the button lacks of its natural width.
                width: Math.min(implicitWidth, implicitWidth + control.width - control.implicitWidth)
                text: control.text
                color: control.ink
                font.weight: control.kind === "primary" ? Font.Medium : Font.Normal
            }
        }
    }
}
