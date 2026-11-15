import QtQuick
import Showrunner

// One part of the builder rail: a token chip, typed text, an empty place to type, or an optional group. A token
// dropped on the left half of a part goes before it, on the right half after it; on an empty place, into it.
Item {
    id: part

    required property var modelData
    property int lineHeight: Theme.row_lg
    readonly property string kind: modelData.kind

    implicitWidth: loader.implicitWidth
    implicitHeight: Math.max(lineHeight, loader.implicitHeight)

    // The piece index a drop at `x` goes before.
    function target(x) {
        if (kind === "slot")
            return modelData.at
        const before = x < width / 2
        if (kind === "group")
            return before ? modelData.at : modelData.end + 1
        return before ? modelData.at : modelData.at + 1
    }

    DropArea {
        id: drop

        anchors.fill: parent
        keys: ["token"]
        onDropped: event => {
            const name = event.source.tokenName
            const from = event.source.from
            const at = part.target(event.x)
            event.accept()
            // Later, so the dragged chip is not rebuilt inside its own drag handler.
            Qt.callLater(() => from >= 0 ? app.rail_move(from, at) : app.rail_insert(at, name))
        }
    }

    Loader {
        id: loader

        anchors.verticalCenter: parent.verticalCenter
        sourceComponent: part.kind === "token" ? chip : part.kind === "group" ? null : text
        Component.onCompleted: if (part.kind === "group") setSource("RailGroup.qml", {"group": part.modelData})
    }

    Component {
        id: chip

        RailChip {
            token: part.modelData
        }
    }

    Component {
        id: text

        RailText {
            piece: part.modelData
        }
    }

    Rectangle {
        visible: drop.containsDrag
        width: Theme.underline
        height: part.height
        x: part.kind === "slot" ? (part.width - width) / 2 : drop.drag.x < part.width / 2 ? 0 : part.width - width
        color: Theme.control
    }
}
