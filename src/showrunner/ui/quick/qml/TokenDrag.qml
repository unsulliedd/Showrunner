import QtQuick
import Showrunner

// Makes its parent a token that can be dragged onto the builder rail. While the drag runs a ghost chip follows the
// pointer over the whole window; dropped on the rail, the rail inserts the token (`from` -1) or moves the piece at
// `from`. The ghost carries what the drop needs, since the source chip may be rebuilt before the drop is handled.
Item {
    id: drag

    property string name
    property string label
    property int from: -1
    readonly property bool active: handler.active

    anchors.fill: parent

    DragHandler {
        id: handler

        target: null

        function follow() {
            const at = ghost.parent.mapFromItem(null, centroid.scenePosition.x, centroid.scenePosition.y)
            ghost.x = at.x - ghost.width / 2
            ghost.y = at.y - ghost.height / 2
        }

        onActiveChanged: {
            if (active) {
                ghost.parent = drag.Window.contentItem
                follow()
                ghost.Drag.active = true
                return
            }
            ghost.Drag.drop()
            ghost.parent = drag
        }
        onCentroidChanged: if (active) follow()
    }

    Rectangle {
        id: ghost

        readonly property string tokenName: drag.name
        readonly property int from: drag.from

        visible: handler.active
        z: 1
        width: ghostLabel.implicitWidth + 2 * Theme.space_lg
        height: Theme.row_md
        radius: Theme.radius_md
        color: Theme.panel_3
        border.width: Theme.stroke
        border.color: Theme.control
        Drag.keys: ["token"]
        Drag.hotSpot.x: width / 2
        Drag.hotSpot.y: height / 2

        UiText {
            id: ghostLabel

            anchors.centerIn: parent
            text: drag.label
            font.weight: Font.Medium
        }
    }
}
