import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A tick box. `ticked` is drawn from the data and never flipped here: a click only says `flipped(on)` with the
// other value, and whoever owns the data changes it, so a box redrawn from Python never disagrees with it. `tone` fills
// a ticked box; an `adding` box is dashed with a plus, for something not yet added that a tick adds.
AbstractButton {
    id: box

    property bool ticked: false
    property string label: ""
    // Said under the box on hover.
    property string tip: ""
    property color tone: Theme.control
    property color mark: Theme.control_ink
    property bool adding: false

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
            color: box.ticked ? box.tone : "transparent"
            border.width: box.adding ? 0 : Theme.stroke
            border.color: box.ticked ? box.tone : box.hovered && box.enabled ? Theme.muted : Theme.line_strong
            opacity: box.enabled ? 1 : 0.5  // a proportion: an unavailable box reads as greyed

            DashedFrame {
                anchors.fill: parent
                visible: box.adding
                radius: Theme.radius_sm
                stroke: box.hovered && box.enabled ? Theme.muted : Theme.line_strong
            }

            Icon {
                anchors.centerIn: parent
                visible: box.ticked || box.adding
                name: box.adding ? "plus" : "check"
                size: Theme.icon_sm
                color: box.adding ? Theme.faint : box.mark
            }
        }
    }

    Tip {
        visible: box.hovered && box.tip !== ""
        text: box.tip
    }
}
