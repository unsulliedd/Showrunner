import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A tick box. `ticked` is drawn from the data and never flipped here: a click only says `flipped(on)` with the
// other value, and whoever owns the data changes it, so a box redrawn from Python never disagrees with it.
AbstractButton {
    id: box

    property bool ticked: false
    property string label: ""
    // Said under the box on hover.
    property string tip: ""

    signal flipped(bool on)

    implicitWidth: Theme.row_sm
    implicitHeight: Theme.row_sm
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.CheckBox
    Accessible.name: label
    Accessible.description: tip
    Accessible.checked: ticked
    onClicked: flipped(!ticked)

    background: Rectangle {
        color: "transparent"
        radius: Theme.radius_sm
        border.width: box.visualFocus ? Theme.stroke : 0
        border.color: Theme.control
    }

    contentItem: Item {
        Rectangle {
            anchors.centerIn: parent
            width: Theme.icon_md + Theme.space_xs
            height: width
            radius: Theme.radius_sm
            color: box.ticked ? Theme.control : "transparent"
            border.width: Theme.stroke
            border.color: box.ticked ? Theme.control : box.hovered && box.enabled ? Theme.muted : Theme.line_strong
            opacity: box.enabled ? 1 : 0.5  // a proportion: an unavailable box reads as greyed

            Icon {
                anchors.centerIn: parent
                visible: box.ticked
                name: "check"
                size: Theme.icon_sm
                color: Theme.control_ink
            }
        }
    }

    Tip {
        visible: box.hovered && box.tip !== ""
        text: box.tip
    }
}
