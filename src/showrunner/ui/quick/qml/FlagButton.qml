import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// The star (default) or F (forced) toggle of a track. `on` is the choice; `held` shows that the file has the flag
// without a choice making it so.
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

    background: Rectangle {
        radius: Theme.radius_sm
        color: control.hovered && control.enabled ? Theme.panel_3 : "transparent"
        border.width: control.visualFocus ? Theme.stroke : 0
        border.color: Theme.control
    }

    contentItem: Item {
        Icon {
            anchors.centerIn: parent
            visible: control.flag === "default"
            name: control.on || control.held ? "star_on" : "star"
            size: Theme.icon_sm
            color: control.on ? Theme.change : control.held ? Theme.muted : Theme.faint
        }

        Rectangle {
            anchors.centerIn: parent
            visible: control.flag === "forced"
            width: Theme.icon_md
            height: Theme.icon_md
            radius: Theme.radius_sm
            color: control.on ? Theme.ink : control.held ? Theme.line_strong : "transparent"
            border.width: control.on ? 0 : Theme.stroke
            border.color: Theme.faint

            UiText {
                anchors.centerIn: parent
                text: Strings.t("tracks.forced_mark")
                color: control.on ? Theme.ground : Theme.faint
                font.pixelSize: Theme.text_xs
                font.weight: Font.Bold
            }
        }
    }
}
