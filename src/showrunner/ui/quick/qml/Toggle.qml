import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// An on/off switch; `label` names it for screen readers. Space or a click flips it.
AbstractButton {
    id: toggle

    property string label: ""

    implicitWidth: Theme.toggle_width
    implicitHeight: Theme.pill
    checkable: true
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.CheckBox
    Accessible.name: label
    Accessible.checked: checked

    background: Rectangle {
        radius: height / 2
        color: toggle.checked ? Theme.control : Theme.panel_3
        border.width: toggle.visualFocus ? Theme.stroke * 2 : Theme.stroke
        border.color: toggle.visualFocus ? Theme.ink : toggle.checked ? Theme.control : Theme.line_strong
        opacity: toggle.enabled ? 1 : 0.5  // a proportion: an unavailable switch reads as greyed

        Rectangle {
            x: toggle.checked ? parent.width - width - Theme.space_xs - Theme.stroke : Theme.space_xs + Theme.stroke
            anchors.verticalCenter: parent.verticalCenter
            width: parent.height - 2 * (Theme.space_xs + Theme.stroke)
            height: width
            radius: width / 2
            color: toggle.checked ? Theme.control_ink : Theme.muted
        }
    }

    contentItem: Item {}
}
