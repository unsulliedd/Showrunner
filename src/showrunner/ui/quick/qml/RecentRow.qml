import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A folder opened before: its name and how long ago; a click reads it again. A right click, the Menu key or Shift+F10
// opens its menu: Open, and Remove from recent, which only takes it off the list.
AbstractButton {
    id: entry

    required property var modelData

    objectName: "recentRow"
    width: parent ? parent.width : 0
    height: Theme.row_lg + Theme.space_xs
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.Button
    Accessible.name: modelData.name
    onClicked: app.open_recent(modelData.path)

    function openMenu(x, y) {
        menu.popup(entry, x, y)
    }

    Keys.onMenuPressed: openMenu(width / 2, height)
    Keys.onPressed: event => {
        if (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier)) {
            openMenu(width / 2, height)
            event.accepted = true
        }
    }

    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: point => entry.openMenu(point.position.x, point.position.y)
    }

    ActionMenu {
        id: menu

        objectName: "recentMenu"
        actions: app.recent_actions()
        onPicked: key => {
            const path = entry.modelData.path
            // Later, so that the row is not freed while its own menu is still closing.
            Qt.callLater(() => key === "remove" ? app.remove_recent(path) : app.open_recent(path))
        }
    }

    background: Rectangle {
        x: -Theme.space_sm
        width: parent.width + 2 * Theme.space_sm
        radius: Theme.radius_md
        color: entry.hovered ? Theme.panel_2 : "transparent"
        border.width: entry.visualFocus ? Theme.stroke : 0
        border.color: Theme.control
    }

    contentItem: Item {
        Icon {
            id: folder

            anchors.verticalCenter: parent.verticalCenter
            name: "folder"
        }

        UiText {
            anchors.left: folder.right
            anchors.leftMargin: Theme.space_lg
            anchors.right: when.left
            anchors.rightMargin: Theme.space_md
            anchors.verticalCenter: parent.verticalCenter
            text: entry.modelData.name
            font.weight: Font.Medium
        }

        UiText {
            id: when

            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: entry.modelData.when
            color: Theme.muted
            font.pixelSize: Theme.text_sm
        }
    }
}
