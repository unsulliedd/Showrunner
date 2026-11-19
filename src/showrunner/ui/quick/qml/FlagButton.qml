import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// The D (default) or F (forced) toggle of a track. `on` is the choice; `held` shows that the file has the flag
// without a choice making it so. An unset flag is a faint letter, framed under the pointer and with the focus.
AbstractButton {
    id: control

    property string flag: "default"
    property bool on: false
    property bool held: false
    property int side: Theme.row_sm

    implicitWidth: side
    implicitHeight: side
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.CheckBox
    Accessible.checked: on
    Accessible.name: Strings.t("tracks.flag_tip." + flag)
    ToolTip.visible: hovered
    ToolTip.text: Accessible.name

    background: Rectangle {
        radius: Theme.radius_sm
        color: control.hovered && control.enabled ? Theme.panel_3 : "transparent"
        border.width: control.visualFocus || control.hovered && control.enabled ? Theme.stroke : 0
        border.color: control.visualFocus ? Theme.control : Theme.line_strong
    }

    contentItem: Item {
        FlagMark {
            anchors.centerIn: parent
            flag: control.flag
            on: control.on
            held: control.held
        }
    }
}
