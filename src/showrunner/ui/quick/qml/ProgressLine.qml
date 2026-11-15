import QtQuick
import Showrunner

// A thin bar filled to `value` (0 to 1).
Rectangle {
    id: line

    property real value: 0
    property color fill: Theme.control

    implicitHeight: Theme.space_xs
    radius: height / 2
    color: Theme.panel_3
    Accessible.role: Accessible.ProgressBar

    Rectangle {
        width: parent.width * Math.max(0, Math.min(1, line.value))
        height: parent.height
        radius: parent.radius
        color: line.fill
    }
}
