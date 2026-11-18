import QtQuick
import Showrunner

// A handle that moves what it belongs to along one axis: dragged, it reports how many places it went on release;
// focused, Ctrl with the arrow keys of its axis moves one place. Where that lands is the controller's to decide.
Item {
    id: grip

    property bool vertical: false
    // The length of one place along the axis, in pixels.
    property real step: 1
    property string label
    readonly property bool active: drag.active
    // How far the drag has gone, for what moves under the pointer and for where it would land.
    readonly property real offset: drag.active ? (vertical ? drag.activeTranslation.y : drag.activeTranslation.x) : 0
    readonly property int places: Math.round(offset / step)

    signal moved(int places)

    implicitWidth: Theme.icon_md
    implicitHeight: Theme.icon_md
    activeFocusOnTab: true
    Accessible.role: Accessible.Grip
    Accessible.name: label
    Keys.onPressed: event => {
        if (!(event.modifiers & Qt.ControlModifier))
            return
        if (event.key === (vertical ? Qt.Key_Up : Qt.Key_Left))
            grip.moved(-1)
        else if (event.key === (vertical ? Qt.Key_Down : Qt.Key_Right))
            grip.moved(1)
        else
            return
        event.accepted = true
    }

    Rectangle {
        anchors.fill: parent
        visible: grip.activeFocus || hover.hovered || grip.active
        radius: Theme.radius_sm
        color: grip.activeFocus ? "transparent" : Theme.panel_3
        border.width: grip.activeFocus ? Theme.stroke : 0
        border.color: Theme.control
    }

    HoverHandler {
        id: hover

        cursorShape: grip.active ? Qt.ClosedHandCursor : Qt.OpenHandCursor
    }

    Icon {
        anchors.centerIn: parent
        name: "grip"
        size: Theme.icon_sm
        color: grip.active || grip.activeFocus ? Theme.control : Theme.faint
    }

    DragHandler {
        id: drag

        target: null
        xAxis.enabled: !grip.vertical
        yAxis.enabled: grip.vertical
        // The translation is gone once the drag ends, so the last one is kept for the release.
        property int reached: 0

        onActiveTranslationChanged: if (active) reached = grip.places
        onActiveChanged: {
            if (active)
                return
            const places = reached
            reached = 0
            if (places !== 0)
                grip.moved(places)
        }
    }
}
