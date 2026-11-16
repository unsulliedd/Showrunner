import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A bar between two stacked panels that sets the height of the one above it: drag it, or press Up and Down while it
// has focus. `value` is that height now; the owner clamps what `adjusted` asks for and keeps the result, and
// `committed` says the user has let go, so the owner saves once per move instead of once per pixel.
Item {
    id: bar

    property int value: 0
    // Where the pointer was in the window and what `value` was when the drag began; the bar itself moves as the
    // panels do, so its own coordinates cannot measure the drag.
    property real pressedAt: 0
    property int pressedValue: 0

    signal adjusted(int height)
    signal committed

    implicitHeight: Theme.panel_gap
    activeFocusOnTab: true
    Accessible.role: Accessible.Splitter
    Accessible.name: Strings.t("overview.separator")
    Keys.onUpPressed: adjusted(value - Theme.separator_step)
    Keys.onDownPressed: adjusted(value + Theme.separator_step)
    Keys.onReleased: event => {
        if (!event.isAutoRepeat && (event.key === Qt.Key_Up || event.key === Qt.Key_Down))
            committed()
    }

    Rectangle {
        anchors.centerIn: parent
        width: Theme.handle_length
        height: Theme.underline
        radius: Theme.underline / 2
        color: Theme.control
        visible: area.containsMouse || area.pressed || bar.activeFocus
    }

    MouseArea {
        id: area

        anchors.fill: parent
        hoverEnabled: true
        preventStealing: true
        cursorShape: Qt.SplitVCursor
        onPressed: mouse => {
            bar.pressedAt = mapToGlobal(mouse.x, mouse.y).y
            bar.pressedValue = bar.value
        }
        onPositionChanged: mouse => {
            if (pressed)
                bar.adjusted(bar.pressedValue + Math.round(mapToGlobal(mouse.x, mouse.y).y - bar.pressedAt))
        }
        onReleased: bar.committed()
    }
}
