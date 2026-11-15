import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A square button that is only an icon; `label` names it for screen readers.
AbstractButton {
    id: control

    property string iconName
    property string label
    property bool active: false

    implicitWidth: Theme.row_md
    implicitHeight: Theme.row_md
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.Button
    Accessible.name: label

    background: Rectangle {
        radius: Theme.radius_md
        color: control.active ? Theme.control_soft : control.hovered && control.enabled ? Theme.panel_3 : "transparent"
        border.width: control.visualFocus ? Theme.stroke : 0
        border.color: Theme.control
    }

    contentItem: Item {
        Icon {
            anchors.centerIn: parent
            name: control.iconName
            color: !control.enabled ? Theme.line_strong : control.active ? Theme.control : Theme.muted
        }
    }
}
