import QtQuick
import Showrunner

// A divider between two columns that sets the width of the one left of it: drag it, or press Left and Right while it
// has focus. `value` is that width now; the owner clamps what `adjusted` asks for and keeps the result, and
// `committed` says the user has let go, so the owner saves once per move instead of once per pixel.
Item {
    id: bar

    property int value: 0
    // What a screen reader calls the divider: the column whose width it sets.
    property string name
    // Where the pointer was in the window and what `value` was when the drag began; the divider moves with the
    // column, so its own coordinates cannot measure the drag.
    property real pressedAt: 0
    property int pressedValue: 0

    signal adjusted(int width)
    signal committed

    implicitWidth: Theme.space_md
    activeFocusOnTab: true
    Accessible.role: Accessible.Splitter
    Accessible.name: name
    Keys.onLeftPressed: adjusted(value - Theme.separator_step)
    Keys.onRightPressed: adjusted(value + Theme.separator_step)
    Keys.onReleased: event => {
        if (!event.isAutoRepeat && (event.key === Qt.Key_Left || event.key === Qt.Key_Right))
            committed()
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        height: parent.height
        width: area.containsMouse || area.pressed || bar.activeFocus ? Theme.underline : Theme.stroke
        color: area.containsMouse || area.pressed || bar.activeFocus ? Theme.control : Theme.line
    }

    MouseArea {
        id: area

        anchors.fill: parent
        hoverEnabled: true
        preventStealing: true
        cursorShape: Qt.SplitHCursor
        onPressed: mouse => {
            bar.pressedAt = mapToGlobal(mouse.x, mouse.y).x
            bar.pressedValue = bar.value
        }
        onPositionChanged: mouse => {
            if (pressed)
                bar.adjusted(bar.pressedValue + Math.round(mapToGlobal(mouse.x, mouse.y).x - bar.pressedAt))
        }
        onReleased: bar.committed()
    }
}
